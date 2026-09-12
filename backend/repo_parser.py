import json
import re
import shutil
import tarfile
from collections import Counter
from pathlib import Path
from .config import settings
from .security import safe_join

IGNORED_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".cache", "__pycache__", ".venv", "venv", "vendor", "target"}
IGNORED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".mov", ".avi", ".mp3", ".wav", ".pdf", ".zip", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".bin"}
SECRET_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "credentials.json", "service-account.json", "credentials.yml"}
LANGUAGES = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".c": "C", ".cpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".dart": "Dart", ".html": "HTML", ".css": "CSS", ".sh": "Shell"}
IMPORTANT = {"readme.md", "main.py", "app.py", "server.py", "index.js", "index.ts", "package.json", "requirements.txt", "pyproject.toml", "dockerfile", "docker-compose.yml", "tsconfig.json"}

def extract_archive(archive: Path, workspace: Path) -> Path:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    extracted = 0
    try:
        with tarfile.open(archive, "r:*") as source:
            members = source.getmembers()
            if len(members) > settings.max_archive_members:
                raise ValueError("Archive contains too many members.")
            for member in members:
                if not member.isfile() and not member.isdir():
                    continue
                relative = Path(*Path(member.name).parts[1:])
                destination = safe_join(workspace, str(relative))
                if member.isfile():
                    extracted += member.size
                    if extracted > settings.max_extracted_bytes:
                        raise ValueError("Extracted repository exceeds the configured size limit.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    destination.mkdir(exist_ok=True)
                else:
                    with source.extractfile(member) as input_file, destination.open("wb") as output:
                        shutil.copyfileobj(input_file, output, 1024 * 64)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    return workspace

def _safe_file(path: Path) -> bool:
    if path.name.lower() in SECRET_NAMES or path.suffix.lower() in IGNORED_EXTENSIONS or path.stat().st_size > settings.max_file_bytes:
        return False
    return not any(part.lower() in IGNORED_DIRS for part in path.parts)

def scan_repository(root: Path) -> dict:
    files, directories, extensions, languages, important = [], set(), Counter(), Counter(), []
    total_size = 0
    for path in root.rglob("*"):
        if path.is_dir():
            directories.add(str(path.relative_to(root)))
            continue
        if not _safe_file(path):
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        size = path.stat().st_size
        total_size += size
        suffix = path.suffix.lower()
        extensions[suffix or "[none]"] += 1
        if suffix in LANGUAGES:
            languages[LANGUAGES[suffix]] += 1
        if path.name.lower() in IMPORTANT or any(token in relative.lower() for token in ("/routes/", "/api/", "/core/", "/config")):
            important.append(relative)
        files.append({"path": relative, "size": size})
    frameworks = detect_frameworks(root, files)
    return {"file_count": len(files), "directory_count": len(directories), "total_size": total_size, "extensions": dict(extensions), "languages": dict(languages), "frameworks": frameworks, "top_level": sorted({item.split("/")[0] for item in [f["path"] for f in files]}), "files": files, "important_files": rank_important(files, important), "readmes": [f["path"] for f in files if "readme" in f["path"].lower()]}

def read_selected(root: Path, paths: list[str], limit: int = 24) -> list[dict]:
    selected = []
    for relative in paths[:limit]:
        path = safe_join(root, relative)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = redact_secrets(text)
        selected.append({"path": relative, "content": text[:12000]})
    return selected

def redact_secrets(text: str) -> str:
    text = re.sub(r"(?im)(['\"]?(?:api[_-]?key|access[_-]?key|secret|password|passwd|token|authorization|client_secret)['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.DOTALL)
    text = re.sub(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b", "[REDACTED TOKEN]", text)
    text = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED TOKEN]", text)
    return text

def rank_important(files, candidates):
    names = set(candidates)
    for item in files:
        path = item["path"]
        name = path.rsplit("/", 1)[-1].lower()
        score = (100 if name in IMPORTANT else 0) + (20 if "/src/" in path else 0) + (15 if any(x in name for x in ("route", "auth", "database", "config")) else 0)
        if score:
            names.add(path)
    return sorted(names, key=lambda item: (0 if item.rsplit("/", 1)[-1].lower() in IMPORTANT else 1, item))[:40]

def detect_frameworks(root: Path, files: list[dict]) -> list[str]:
    names = {item["path"].rsplit("/", 1)[-1].lower() for item in files}
    text = ""
    for candidate in ("requirements.txt", "pyproject.toml", "package.json"):
        path = root / candidate
        if path.exists() and path.stat().st_size <= settings.max_file_bytes:
            text += path.read_text(encoding="utf-8", errors="ignore").lower()
    checks = {"FastAPI": "fastapi", "Flask": "flask", "Django": "django", "React": "react", "Next.js": "next", "Vue": "vue", "Angular": "angular", "Express": "express", "Spring": "spring", "Flutter": "flutter", ".NET": "aspnetcore"}
    return [framework for framework, marker in checks.items() if marker in text]
