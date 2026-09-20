import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from .ai_router import configured_providers, generate_analysis, parse_focused_result, provider_priority, set_provider_priority
from .config import FRONTEND_ROOT, WORKSPACE_ROOT, settings
from .database import create_analysis, delete_analysis, get_analysis, init_db, list_analyses, update_analysis
from .focused_analysis import REPOSITORY_TYPES, build_focused_prompt, discover_candidates, enrich_focused_result, read_evidence
from .github_service import GitHubService
from .prompt_builder import build_prompt
from .repo_parser import extract_archive, read_selected, scan_repository
from .security import parse_github_url, workspace_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
_job_lock = asyncio.Lock()
_analysis_semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)
_active_jobs = 0
_workspace_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    yield

app = FastAPI(title="GitHub Repo Analyzer", version="1.0.0", lifespan=lifespan)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

class RepositoryRequest(BaseModel):
    url: HttpUrl

class AdvancedSettings(BaseModel):
    enabled: bool = False
    repository_type: str = "Auto Detect"
    question: str = ""

class AnalyzeRequest(BaseModel):
    url: HttpUrl
    advanced: AdvancedSettings | None = None

class PriorityRequest(BaseModel):
    priority: list[str]

@app.get("/api/health")
async def health():
    return {"status": "ok", "providers_configured": [provider.name for provider in configured_providers()]}

@app.post("/api/repositories/validate")
async def validate_repository(request: RepositoryRequest):
    try:
        repository = await GitHubService().validate(str(request.url))
    except Exception as error:
        raise HTTPException(400, str(error)) from error
    return repository.__dict__

@app.post("/api/analyze", status_code=202)
async def analyze(request: AnalyzeRequest, tasks: BackgroundTasks):
    try:
        parsed = parse_github_url(str(request.url))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    advanced = None
    if request.advanced is not None and request.advanced.enabled:
        question = (request.advanced.question or "").strip()
        if not question:
            raise HTTPException(400, "A question is required when Advanced Analysis is enabled.")
        if len(question) > 2000:
            raise HTTPException(400, "The question must be 2000 characters or fewer.")
        if request.advanced.repository_type not in REPOSITORY_TYPES:
            raise HTTPException(400, f"Repository type must be one of: {', '.join(REPOSITORY_TYPES)}.")
        advanced = request.advanced
    global _active_jobs
    async with _job_lock:
        capacity = settings.max_concurrent_analyses + settings.max_pending_analyses
        if _active_jobs >= capacity:
            raise HTTPException(429, "Analysis queue is full. Try again later.")
        _active_jobs += 1
    analysis_id = uuid.uuid4().hex
    create_analysis(analysis_id, str(request.url), parsed["owner"], parsed["name"], parsed["ref"] or None, analysis_mode="focused" if advanced else "standard", repository_type=advanced.repository_type if advanced else None, user_question=advanced.question.strip() if advanced else None)
    tasks.add_task(run_analysis, analysis_id, str(request.url), advanced)
    return {"analysis_id": analysis_id, "status": "queued"}

async def run_analysis(analysis_id: str, url: str, advanced: AdvancedSettings | None = None) -> None:
    global _active_jobs
    archive = None
    workspace = None
    workspace_key = None
    acquired = False
    try:
        await _analysis_semaphore.acquire()
        acquired = True
        update_analysis(analysis_id, status="validating")
        repository = await GitHubService().validate(url)
        update_analysis(analysis_id, status="downloading")
        workspace_key = workspace_for(repository.owner, repository.name, repository.ref)
        workspace = WORKSPACE_ROOT / workspace_key
        lock = _workspace_locks[workspace_key]
        await lock.acquire()
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temporary:
            archive = Path(temporary.name)
        await GitHubService().download_archive(repository, archive)
        update_analysis(analysis_id, status="extracting")
        await asyncio.to_thread(extract_archive, archive, workspace)
        update_analysis(analysis_id, status="scanning")
        scan = await asyncio.to_thread(scan_repository, workspace)
        if advanced is not None:
            update_analysis(analysis_id, status="interpreting")
            question = advanced.question.strip()
            repository_type = advanced.repository_type or "Auto Detect"
            update_analysis(analysis_id, status="discovering")
            discovery = await asyncio.to_thread(discover_candidates, workspace, scan, question, repository_type)
            update_analysis(analysis_id, status="extracting_evidence")
            evidence = await asyncio.to_thread(read_evidence, workspace, discovery)
            system, prompt = await asyncio.to_thread(build_focused_prompt, repository, scan, question, repository_type, evidence)
            update_analysis(analysis_id, status="analyzing")
            result, provider = await generate_analysis(prompt, system, parse=parse_focused_result)
            result["question"] = question
            result = await asyncio.to_thread(enrich_focused_result, result, repository, scan, evidence)
            update_analysis(analysis_id, status="validating_result")
            update_analysis(analysis_id, status="completed", score=None, summary=result.get("answer", ""), provider=provider, result_json=json.dumps(result))
        else:
            update_analysis(analysis_id, status="building_context")
            selected = await asyncio.to_thread(read_selected, workspace, scan["important_files"])
            system, prompt = build_prompt(repository, scan, selected)
            update_analysis(analysis_id, status="analyzing")
            result, provider = await generate_analysis(prompt, system)
            update_analysis(analysis_id, status="validating_result")
            update_analysis(analysis_id, status="completed", score=result["overall_score"], summary=result.get("executive_summary", ""), provider=provider, result_json=json.dumps(result))
    except Exception as error:
        logger.exception("analysis_failed id=%s", analysis_id)
        update_analysis(analysis_id, status="failed", error=str(error))
    finally:
        if workspace and workspace.exists() and get_analysis(analysis_id) and get_analysis(analysis_id).get("status") == "failed":
            shutil.rmtree(workspace, ignore_errors=True)
        if workspace_key and workspace_key in _workspace_locks and _workspace_locks[workspace_key].locked():
            _workspace_locks[workspace_key].release()
        if archive:
            archive.unlink(missing_ok=True)
        async with _job_lock:
            _active_jobs = max(0, _active_jobs - 1)
        if acquired:
            _analysis_semaphore.release()

@app.get("/api/analyze/{analysis_id}")
async def analysis_status(analysis_id: str):
    result = get_analysis(analysis_id)
    if not result:
        raise HTTPException(404, "Analysis not found.")
    return result

@app.get("/api/analyses")
async def analyses():
    return list_analyses()

@app.get("/api/analyses/{analysis_id}")
async def analysis_detail(analysis_id: str):
    return await analysis_status(analysis_id)

@app.delete("/api/analyses/{analysis_id}")
async def remove_analysis(analysis_id: str):
    analysis = get_analysis(analysis_id)
    if not analysis:
        return JSONResponse(status_code=404, content={"error": "Analysis not found"})
    if not delete_analysis(analysis_id):
        return JSONResponse(status_code=404, content={"error": "Analysis not found"})
    workspace = WORKSPACE_ROOT / workspace_for(analysis["owner"], analysis["name"], analysis.get("ref") or "")
    shutil.rmtree(workspace, ignore_errors=True)
    return {"deleted": True}

@app.get("/api/settings/status")
async def settings_status():
    return {"providers": {"Gemini": bool(settings.gemini_api_key), "Groq": bool(settings.groq_api_key), "OpenRouter": bool(settings.openrouter_api_key), "Hugging Face": bool(settings.hf_token)}, "github_token": bool(settings.github_token), "limits": {"max_repository_bytes": settings.max_repository_bytes, "max_extracted_bytes": settings.max_extracted_bytes, "max_file_bytes": settings.max_file_bytes, "max_prompt_bytes": settings.max_prompt_bytes, "max_archive_members": settings.max_archive_members, "max_concurrent_analyses": settings.max_concurrent_analyses, "max_pending_analyses": settings.max_pending_analyses}, "priority": provider_priority}

@app.post("/api/settings/priority")
async def update_priority(request: PriorityRequest):
    try:
        set_provider_priority(request.priority)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"priority": provider_priority}

app.mount("/static", StaticFiles(directory=FRONTEND_ROOT), name="static")

@app.get("/{page}.html")
async def page(page: str):
    target = FRONTEND_ROOT / f"{page}.html"
    if not target.exists():
        raise HTTPException(404, "Page not found")
    return FileResponse(target)

@app.get("/")
async def root():
    return FileResponse(FRONTEND_ROOT / "index.html")
