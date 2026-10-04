import json
import logging
import math
from .local_ai import LocalAIClient, LocalAIError

logger = logging.getLogger(__name__)


def _safe_debug_snippet(raw: str | None, limit: int = 500) -> str:
    value = str(raw or "")
    return value[:limit]


def _safe_debug_suffix(raw: str | None, limit: int = 200) -> str:
    value = str(raw or "")
    if len(value) <= limit:
        return value
    return value[-limit:]


def _log_local_ai_parse_failure(provider: str, attempt: int, raw: str | None, reason: str) -> None:
    value = raw or ""
    preview = _safe_debug_snippet(value)
    suffix = _safe_debug_suffix(value)
    logger.warning(
        "local_ai_json_parse_failed provider=%s attempt=%s length=%s preview=%r suffix=%r reason=%s",
        provider,
        attempt,
        len(value),
        preview,
        suffix,
        reason,
    )

class AnalysisResponseError(Exception):
    def __init__(self, message: str, category: str = "invalid_response"):
        super().__init__(message)
        self.category = category

local_ai = LocalAIClient()

def _coerce_string_list(value):
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if value is None:
        return []
    return [str(value)] if str(value).strip() else []


def _fallback_repository_payload(repository):
    if repository is None:
        return {"name": "", "owner": "", "url": "", "description": ""}
    return {
        "name": getattr(repository, "name", ""),
        "owner": getattr(repository, "owner", ""),
        "url": getattr(repository, "url", ""),
        "description": getattr(repository, "description", ""),
    }


def _extract_file_features(selected):
    features = []
    keywords = [
        ("FastAPI", "API endpoints and async request handling"),
        ("Flask", "lightweight web routes and app wiring"),
        ("React", "interactive front-end UI components"),
        ("Django", "structured server-side application framework"),
        ("Express", "Node-based API server"),
        ("auth", "authentication and authorization flows"),
        ("database", "data persistence and storage logic"),
        ("test", "test coverage and validation behavior"),
        ("docker", "containerization support"),
        ("route", "routing and navigation logic"),
    ]
    for entry in selected or []:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "")
        for keyword, description in keywords:
            if keyword.lower() in content.lower() and description not in features:
                features.append(description)
    return features


def build_repo_fallback_report(repository, scan, selected):
    repo_info = _fallback_repository_payload(repository)
    frameworks = _coerce_string_list((scan or {}).get("frameworks"))
    languages = []
    language_map = (scan or {}).get("languages")
    if isinstance(language_map, dict):
        languages = [str(name) for name in language_map.keys()]
    selected_files = []
    for entry in selected or []:
        if isinstance(entry, dict):
            value = entry.get("path") or entry.get("file") or ""
        else:
            value = str(entry)
        if value:
            selected_files.append(str(value))
    file_hints = [item for item in selected_files[:6] if item]
    top_level = _coerce_string_list((scan or {}).get("top_level"))
    important = _coerce_string_list((scan or {}).get("important_files"))
    file_features = _extract_file_features(selected)
    tech_stack = frameworks + languages
    if not tech_stack:
        tech_stack = ["Repository codebase"]
    summary = f"This repository appears to be a {', '.join(tech_stack[:3])} project."
    if file_hints:
        summary = f"This repository appears to be a {', '.join(tech_stack[:3])} project focused on {', '.join(file_hints[:3])}."
    architecture = "Full-stack application" if len(frameworks) > 1 else "Application repository"
    if frameworks and "FastAPI" in frameworks:
        architecture = "FastAPI-backed application"
    elif frameworks and "React" in frameworks:
        architecture = "React front-end with supporting backend code"
    score = 62 + min(20, len(frameworks) * 6) + min(10, len(languages) * 2) + min(8, len(important) // 4)
    score = max(0, min(100, score))
    strengths = [
        "Clearly organized project structure",
        "Multiple framework and language signals across the repository",
        "Key files and app entry points were identified in the repository scan",
    ]
    if file_features:
        strengths.extend(file_features[:3])
    weaknesses = [
        "Detailed business logic and feature intent rely on repository evidence rather than a full LLM narrative",
        "Some implementation details may be missing if the repository is sparse or uses non-standard conventions",
    ]
    if not file_features:
        weaknesses.append("Repository content inspection was limited to structural and metadata evidence.")
    report = {
        "repository": repo_info,
        "executive_summary": summary,
        "project_purpose": "The repository contains application code and supporting project files, with a visible structure that suggests a deployable software project.",
        "technology_stack": tech_stack,
        "architecture": {"type": architecture, "description": "Repository evidence indicates an application with a clear project layout, code entry points, and supporting front-end or service components."},
        "important_files": important[:10] if important else file_hints[:10],
        "directory_overview": top_level[:10] if top_level else ["source", "app", "frontend", "tests"],
        "key_features": [
            "Detectable project structure with application entry points",
            "Evidence of framework and language usage across the codebase",
            "Supporting configuration and documentation files",
        ] + file_features[:3],
        "strengths": strengths,
        "weaknesses": weaknesses,
        "security_findings": ["No explicit security review was performed; review secrets and auth flows before deployment."],
        "code_quality": ["Repository structure is consistent enough to support maintainable application development."],
        "performance_considerations": ["Performance should be verified against real usage patterns once runtime behavior is measured."],
        "testing": ["Repository scan found test-related files when present, but explicit execution evidence is not guaranteed."],
        "documentation": ["The project appears to include documentation and project metadata files."],
        "dependencies": ["Dependency configuration appears to exist in project metadata files."],
        "deployment": ["Deployment configuration should be confirmed from environment and infrastructure files."],
        "technical_debt": ["The repository may carry unknown debt until runtime and code quality checks are performed."],
        "recommendations": [
            "Review the runtime entry points and configuration files before deployment.",
            "Validate authentication, secret management, and environment variables in production.",
            "Confirm test coverage and deployment configuration for a release-ready rollout.",
        ],
        "overall_score": score,
        "confidence": "medium",
        "limitations": [
            "Summary generated from repository scan evidence because the model response was unavailable or incomplete.",
            "Repository-level inference may miss nuances that require deeper runtime or implementation review.",
        ],
    }
    return report


def _normalize_result(result, repository=None, scan=None, selected=None):
    if not isinstance(result, dict):
        raise AnalysisResponseError("Local AI response did not match the analysis schema", "invalid_schema")
    fallback = build_repo_fallback_report(repository, scan, selected)
    if result.get("summary") and not result.get("executive_summary"):
        result["executive_summary"] = str(result["summary"])
    if result.get("executive_summary") and not result.get("summary"):
        result["summary"] = str(result["executive_summary"])
    result.setdefault("repository", _fallback_repository_payload(repository))
    if not result["repository"]:
        result["repository"] = _fallback_repository_payload(repository)
    result.setdefault("executive_summary", "")
    result.setdefault("summary", result["executive_summary"])
    result.setdefault("project_purpose", "")
    result.setdefault("technology_stack", [])
    result.setdefault("architecture", {"type": "", "description": ""})
    result.setdefault("important_files", [])
    result.setdefault("directory_overview", [])
    result.setdefault("key_features", [])
    result.setdefault("strengths", [])
    result.setdefault("weaknesses", [])
    result.setdefault("security_findings", [])
    result.setdefault("code_quality", [])
    result.setdefault("performance_considerations", [])
    result.setdefault("testing", [])
    result.setdefault("documentation", [])
    result.setdefault("dependencies", [])
    result.setdefault("deployment", [])
    result.setdefault("technical_debt", [])
    result.setdefault("recommendations", [])
    result.setdefault("overall_score", 0)
    result.setdefault("confidence", "")
    result.setdefault("limitations", [])

    result["technology_stack"] = _coerce_string_list(result.get("technology_stack")) if result.get("technology_stack") else fallback["technology_stack"]
    result["important_files"] = _coerce_string_list(result.get("important_files")) if result.get("important_files") else fallback["important_files"]
    result["directory_overview"] = _coerce_string_list(result.get("directory_overview")) if result.get("directory_overview") else fallback["directory_overview"]
    result["key_features"] = _coerce_string_list(result.get("key_features")) if result.get("key_features") else fallback["key_features"]
    result["strengths"] = _coerce_string_list(result.get("strengths")) if result.get("strengths") else fallback["strengths"]
    result["weaknesses"] = _coerce_string_list(result.get("weaknesses")) if result.get("weaknesses") else fallback["weaknesses"]
    result["security_findings"] = _coerce_string_list(result.get("security_findings")) if result.get("security_findings") else fallback["security_findings"]
    result["code_quality"] = _coerce_string_list(result.get("code_quality")) if result.get("code_quality") else fallback["code_quality"]
    result["performance_considerations"] = _coerce_string_list(result.get("performance_considerations")) if result.get("performance_considerations") else fallback["performance_considerations"]
    result["testing"] = _coerce_string_list(result.get("testing")) if result.get("testing") else fallback["testing"]
    result["documentation"] = _coerce_string_list(result.get("documentation")) if result.get("documentation") else fallback["documentation"]
    result["dependencies"] = _coerce_string_list(result.get("dependencies")) if result.get("dependencies") else fallback["dependencies"]
    result["deployment"] = _coerce_string_list(result.get("deployment")) if result.get("deployment") else fallback["deployment"]
    result["technical_debt"] = _coerce_string_list(result.get("technical_debt")) if result.get("technical_debt") else fallback["technical_debt"]
    result["recommendations"] = _coerce_string_list(result.get("recommendations")) if result.get("recommendations") else fallback["recommendations"]
    if not isinstance(result.get("limitations"), list):
        result["limitations"] = _coerce_string_list(result.get("limitations")) or fallback["limitations"]
    elif not result["limitations"]:
        result["limitations"] = fallback["limitations"]
    result["repository"] = result.get("repository") or _fallback_repository_payload(repository)
    if not result["executive_summary"]:
        result["executive_summary"] = fallback["executive_summary"]
    result["summary"] = result.get("summary") or result["executive_summary"]
    if not result.get("project_purpose"):
        result["project_purpose"] = fallback["project_purpose"]
    if not isinstance(result.get("architecture"), dict):
        result["architecture"] = fallback["architecture"]
    else:
        architecture = result["architecture"]
        architecture.setdefault("type", fallback["architecture"]["type"])
        architecture.setdefault("description", fallback["architecture"]["description"])
        result["architecture"] = architecture
    score = result.get("overall_score")
    if isinstance(score, bool):
        raise AnalysisResponseError("Local AI response did not match the analysis schema", "invalid_schema")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError) as error:
        raise AnalysisResponseError("Local AI response did not match the analysis schema", "invalid_schema") from error
    if not math.isfinite(numeric_score):
        raise AnalysisResponseError("Local AI response did not match the analysis schema", "invalid_schema")
    result["overall_score"] = max(0, min(100, int(numeric_score)))
    result.setdefault("confidence", fallback["confidence"])
    if not result["confidence"]:
        result["confidence"] = fallback["confidence"]
    return result


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip().removeprefix("\ufeff")
    if "```" not in cleaned:
        return cleaned
    first_fence = cleaned.find("```")
    if first_fence == -1:
        return cleaned
    after_fence = cleaned[first_fence + 3 :].lstrip()
    if after_fence.lower().startswith("json"):
        after_fence = after_fence[4:].lstrip()
    closing = after_fence.find("```")
    if closing == -1:
        return cleaned
    candidate = after_fence[:closing].strip()
    if candidate:
        return candidate
    return cleaned


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise AnalysisResponseError("Local AI returned malformed JSON: no JSON object found.", "invalid_json")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AnalysisResponseError("Local AI returned malformed JSON: unmatched object braces.", "invalid_json")


def _decode_json_object(raw: str):
    if raw is None:
        raise AnalysisResponseError("Local AI returned an empty response.", "empty_response")
    cleaned = str(raw).strip().removeprefix("\ufeff")
    if not cleaned:
        raise AnalysisResponseError("Local AI returned an empty response.", "empty_response")
    cleaned = _strip_json_fence(cleaned)
    if not cleaned:
        raise AnalysisResponseError("Local AI returned an empty response.", "empty_response")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        if "{" not in cleaned:
            raise AnalysisResponseError("Local AI returned malformed JSON: no JSON object found.", "invalid_json") from error
        try:
            candidate = _extract_json_object(cleaned)
            return json.loads(candidate)
        except AnalysisResponseError:
            raise
        except json.JSONDecodeError as decode_error:
            raise AnalysisResponseError(f"Local AI returned malformed JSON: {decode_error.msg} at column {decode_error.colno}.", "invalid_json") from decode_error


def parse_result(raw: str) -> dict:
    result = _decode_json_object(raw)
    return _normalize_result(result)

FOCUSED_STATUS_ALIASES = {
    "implemented": "implemented", "found": "implemented", "yes": "implemented", "working": "implemented",
    "partial": "partial", "partially_implemented": "partial", "partially": "partial", "partial_implementation": "partial", "partly": "partial",
    "referenced_only": "referenced_only", "referenced": "referenced_only", "mentioned": "referenced_only", "documented_only": "referenced_only",
    "not_found": "not_found", "not-found": "not_found", "missing": "not_found", "no": "not_found", "absent": "not_found",
    "uncertain": "uncertain", "unknown": "uncertain", "insufficient": "uncertain", "ambiguous": "uncertain",
}
FOCUSED_STRENGTHS = {"strong", "moderate", "weak", "insufficient"}

def parse_focused_result(raw: str) -> dict:
    result = _decode_json_object(raw)
    if not isinstance(result, dict):
        raise AnalysisResponseError("Local AI response did not match the focused analysis schema", "invalid_schema")
    required = {"status", "answer", "evidence", "evidence_strength"}
    if not required.issubset(result):
        raise AnalysisResponseError("Local AI response did not match the focused analysis schema", "invalid_schema")
    status = FOCUSED_STATUS_ALIASES.get(str(result.get("status", "")).strip().lower().replace(" ", "_"))
    if status is None:
        raise AnalysisResponseError("Local AI response did not match the focused analysis schema", "invalid_schema")
    strength = str(result.get("evidence_strength", "")).strip().lower()
    if strength not in FOCUSED_STRENGTHS:
        raise AnalysisResponseError("Local AI response did not match the focused analysis schema", "invalid_schema")
    evidence = []
    raw_evidence = result.get("evidence")
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if isinstance(item, dict):
                evidence.append({"file": str(item.get("file") or item.get("path") or ""), "symbols": item.get("symbols") if isinstance(item.get("symbols"), list) else [], "reason": str(item.get("reason") or "")})
            elif isinstance(item, str):
                evidence.append({"file": item.strip(), "symbols": [], "reason": ""})
    normalized = {
        "question": str(result.get("question") or ""),
        "status": status,
        "answer": str(result.get("answer") or ""),
        "evidence": evidence,
        "how_it_works": str(result.get("how_it_works") or ""),
        "repository_flow": result.get("repository_flow") if isinstance(result.get("repository_flow"), list) else [],
        "limitations": str(result.get("limitations") or ""),
        "evidence_strength": strength,
    }
    if not normalized["answer"]:
        raise AnalysisResponseError("Local AI response did not match the focused analysis schema", "invalid_schema")
    return normalized

async def generate_analysis(prompt: str, system: str, parse=None, repository=None, scan=None, selected=None) -> tuple[dict, str]:
    processor = parse or parse_result
    retry_system = system
    for attempt in range(1, 3):
        current_system = retry_system if attempt == 1 else f"{retry_system}\nReturn only one valid JSON object and no explanations. Correct the previous malformed output and do not include markdown fences."
        try:
            raw = await local_ai.generate(prompt if attempt == 1 else prompt + "\nYour previous response was invalid JSON. Return only a valid JSON object and nothing else.", current_system)
            result = processor(raw)
            result = _normalize_result(result, repository, scan, selected)
            result["provider"] = "Local AI"
            result["source"] = "local_model_response"
            return result, "Local AI"
        except AnalysisResponseError as error:
            _log_local_ai_parse_failure("gemma", attempt, raw if 'raw' in locals() else None, str(error))
            if attempt == 1:
                continue
            fallback = build_repo_fallback_report(repository, scan, selected)
            fallback["provider"] = "Local AI fallback"
            fallback["source"] = "local_fallback"
            if not fallback.get("summary") and fallback.get("executive_summary"):
                fallback["summary"] = fallback["executive_summary"]
            logger.warning("local_ai_fallback provider=gemma attempts=%s reason=%s", attempt, error)
            return fallback, "Local AI fallback"
        except LocalAIError as error:
            if "empty response" not in str(error).lower() and "invalid analysis response" not in str(error).lower() and "malformed" not in str(error).lower():
                raise
            _log_local_ai_parse_failure("gemma", attempt, None, str(error))
            if attempt == 1:
                continue
            fallback = build_repo_fallback_report(repository, scan, selected)
            fallback["provider"] = "Local AI fallback"
            fallback["source"] = "local_fallback"
            if not fallback.get("summary") and fallback.get("executive_summary"):
                fallback["summary"] = fallback["executive_summary"]
            logger.warning("local_ai_fallback provider=gemma attempts=%s reason=%s", attempt, error)
            return fallback, "Local AI fallback"
    raise LocalAIError("Local AI returned an invalid analysis response. Please retry the analysis.")
