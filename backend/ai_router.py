import json
import logging
import math
import time
import httpx
from .config import settings

logger = logging.getLogger(__name__)

class ProviderError(Exception):
    def __init__(self, message: str, category: str = "provider_error", status: int | None = None):
        super().__init__(message)
        self.category, self.status = category, status

class AIProvider:
    name = ""
    key = ""
    async def generate(self, prompt: str, system: str) -> str:
        raise NotImplementedError

class GeminiProvider(AIProvider):
    name, key = "Gemini", "gemini_api_key"
    async def generate(self, prompt, system):
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}
        async with httpx.AsyncClient(timeout=75) as client:
            response = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
        return _text(response, lambda data: data["candidates"][0]["content"]["parts"][0]["text"])

class GroqProvider(AIProvider):
    name, key = "Groq", "groq_api_key"
    async def generate(self, prompt, system):
        return await _openai_compatible("https://api.groq.com/openai/v1/chat/completions", settings.groq_api_key, "llama-3.3-70b-versatile", prompt, system)

class OpenRouterProvider(AIProvider):
    name, key = "OpenRouter", "openrouter_api_key"
    async def generate(self, prompt, system):
        return await _openai_compatible("https://openrouter.ai/api/v1/chat/completions", settings.openrouter_api_key, "openai/gpt-4o-mini", prompt, system)

class HuggingFaceProvider(AIProvider):
    name, key = "Hugging Face", "hf_token"
    async def generate(self, prompt, system):
        headers = {"Authorization": f"Bearer {settings.hf_token}"}
        body = {"inputs": f"{system}\n\n{prompt}", "parameters": {"max_new_tokens": 3000, "return_full_text": False}}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post("https://router.huggingface.co/hf-inference/models/Qwen/Qwen2.5-72B-Instruct", headers=headers, json=body)
        return _text(response, lambda data: data[0]["generated_text"] if isinstance(data, list) else data["generated_text"])

async def _openai_compatible(url, key, model, prompt, system):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=75) as client:
        response = await client.post(url, headers=headers, json=body)
    return _text(response, lambda data: data["choices"][0]["message"]["content"])

def _text(response, extractor):
    if response.status_code == 429:
        raise ProviderError("Provider rate limited", "rate_limit", response.status_code)
    if response.status_code >= 500:
        raise ProviderError("Provider unavailable", "temporary", response.status_code)
    if response.status_code >= 400:
        raise ProviderError("Provider request rejected", "request_error", response.status_code)
    try:
        text = extractor(response.json()).strip()
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError("Provider returned an unexpected response", "invalid_response") from error
    if not text:
        raise ProviderError("Provider returned an empty response", "invalid_response")
    return text

PROVIDERS = [GeminiProvider(), GroqProvider(), OpenRouterProvider(), HuggingFaceProvider()]
provider_priority = [provider.name for provider in PROVIDERS]

def configured_providers():
    by_name = {provider.name: provider for provider in PROVIDERS}
    return [by_name[name] for name in provider_priority if getattr(settings, by_name[name].key)]

def set_provider_priority(names: list[str]) -> None:
    available = {provider.name for provider in PROVIDERS}
    if set(names) != available or len(names) != len(available):
        raise ValueError("Priority must contain each supported provider exactly once.")
    provider_priority[:] = names

def parse_result(raw: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ProviderError("AI response was not valid JSON", "invalid_json") from error
    required = {"repository", "executive_summary", "technology_stack", "overall_score", "limitations"}
    if not required.issubset(result):
        raise ProviderError("AI response did not match the analysis schema", "invalid_schema")
    score = result.get("overall_score")
    if isinstance(score, bool):
        raise ProviderError("AI response did not match the analysis schema", "invalid_schema")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError) as error:
        raise ProviderError("AI response did not match the analysis schema", "invalid_schema") from error
    if not math.isfinite(numeric_score):
        raise ProviderError("AI response did not match the analysis schema", "invalid_schema")
    result["overall_score"] = max(0, min(100, int(numeric_score)))
    return result

FOCUSED_STATUS_ALIASES = {
    "implemented": "implemented", "found": "implemented", "yes": "implemented", "working": "implemented",
    "partial": "partial", "partially_implemented": "partial", "partially": "partial", "partial_implementation": "partial", "partly": "partial",
    "referenced_only": "referenced_only", "referenced": "referenced_only", "mentioned": "referenced_only", "documented_only": "referenced_only",
    "not_found": "not_found", "not-found": "not_found", "missing": "not_found", "no": "not_found", "absent": "not_found",
    "uncertain": "uncertain", "unknown": "uncertain", "insufficient": "uncertain", "ambiguous": "uncertain",
}
FOCUSED_STRENGTHS = {"strong", "moderate", "weak", "insufficient"}

def parse_focused_result(raw: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ProviderError("AI response was not valid JSON", "invalid_json") from error
    required = {"status", "answer", "evidence", "evidence_strength"}
    if not required.issubset(result):
        raise ProviderError("AI response did not match the focused analysis schema", "invalid_schema")
    status = FOCUSED_STATUS_ALIASES.get(str(result.get("status", "")).strip().lower().replace(" ", "_"))
    if status is None:
        raise ProviderError("AI response did not match the focused analysis schema", "invalid_schema")
    strength = str(result.get("evidence_strength", "")).strip().lower()
    if strength not in FOCUSED_STRENGTHS:
        raise ProviderError("AI response did not match the focused analysis schema", "invalid_schema")
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
        raise ProviderError("AI response did not match the focused analysis schema", "invalid_schema")
    return normalized

async def generate_analysis(prompt: str, system: str, parse=None) -> tuple[dict, str]:
    processor = parse or parse_result
    errors = []
    for attempt, provider in enumerate(configured_providers(), 1):
        started = time.perf_counter()
        try:
            raw = await provider.generate(prompt, system)
            result = processor(raw)
            logger.info("ai_provider_success provider=%s attempt=%s duration_ms=%s", provider.name, attempt, int((time.perf_counter() - started) * 1000))
            return result, provider.name
        except (ProviderError, httpx.HTTPError) as error:
            category = getattr(error, "category", "network")
            errors.append(f"{provider.name}: {category}")
            logger.warning("ai_provider_failure provider=%s attempt=%s category=%s", provider.name, attempt, category)
    if not configured_providers():
        raise RuntimeError("No AI provider configured. Add at least one provider key to .env.")
    raise RuntimeError("All configured AI providers failed: " + ", ".join(errors))
