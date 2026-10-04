"""Manage the project-local Gemma model used for repository analysis."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import MODEL_NAME, settings

logger = logging.getLogger(__name__)


class LocalAIError(RuntimeError):
    """A safe, user-facing local inference failure."""


@dataclass(frozen=True)
class LocalAIInstallation:
    root: Path
    model: Path
    model_name: str
    port: int = 0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _candidate_model_dirs(override: str | Path | None = None) -> list[Path]:
    if override:
        override_path = Path(override).expanduser()
        candidate_paths = [override_path]
        if override_path.name != "gemma-3-1b-it":
            candidate_paths.append(override_path / "models" / "gemma-3-1b-it")
        candidates = candidate_paths
    else:
        project_root = _project_root()
        candidates = [
            project_root / "models" / "gemma-3-1b-it",
            project_root / "models" / "gemma-3-1b-it" / "models" / "gemma-3-1b-it",
        ]
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            normalized = candidate.resolve(strict=False)
        except OSError:
            normalized = candidate
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _has_model_files(model_dir: Path) -> bool:
    if not model_dir.exists() or not model_dir.is_dir():
        return False
    config_file = model_dir / "config.json"
    tokenizer_file = model_dir / "tokenizer_config.json"
    has_weights = any(model_dir.glob("*.safetensors")) or any(model_dir.glob("pytorch_model*.bin"))
    has_tokenizer = any(
        (model_dir / filename).exists()
        for filename in ("tokenizer.json", "tokenizer.model", "spiece.model")
    )
    return config_file.exists() and tokenizer_file.exists() and has_weights and has_tokenizer


def discover_installation(override: str | Path | None = None) -> LocalAIInstallation | None:
    """Find the project-local Gemma model directory without any external drive dependency."""
    for candidate in _candidate_model_dirs(override):
        if not _has_model_files(candidate):
            continue
        root = candidate.parent.parent if candidate.name == "gemma-3-1b-it" else candidate.parent
        return LocalAIInstallation(
            root=root,
            model=candidate,
            model_name=str(settings.local_ai_model_name or MODEL_NAME),
            port=int(getattr(settings, "local_ai_port", 8080)),
        )
    return None


def _local_model_error(override: str | Path | None) -> str:
    message = (
        "Local Gemma model not found. Download google/gemma-3-1b-it into "
        "models/gemma-3-1b-it or run python scripts/download_model.py."
    )
    if override:
        return f"{message} Checked: {Path(override).expanduser()}"
    return message


def extract_chat_content(payload: Any) -> str:
    """Validate the minimum OpenAI-compatible chat completion response shape."""
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LocalAIError("Local AI returned an unexpected response.") from error
    if not isinstance(content, str) or not content.strip():
        raise LocalAIError("Local AI returned an empty response.")
    return content.strip()


class LocalAIClient:
    """Own a single reusable Transformers pipeline bound to the project-local Gemma model."""

    def __init__(self, config=settings) -> None:
        self.config = config
        self.installation: LocalAIInstallation | None = None
        self.pipeline = None
        self.model_loaded = False
        self.actual_port = int(getattr(config, "local_ai_port", 8080))
        self.last_error = _local_model_error(getattr(config, "local_ai_model_dir", None))
        self._start_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    def _installation_is_present(self) -> bool:
        return bool(self.installation and self.installation.model.exists())

    def _discover(self) -> bool:
        override = getattr(self.config, "local_ai_model_dir", None)
        self.installation = discover_installation(override)
        if self.installation is None:
            self.last_error = _local_model_error(override)
            return False
        self.last_error = ""
        logger.info("local_ai_installation_discovered model=%s", self.installation.model)
        return True

    def _load_pipeline(self) -> bool:
        if self.pipeline is not None and self.model_loaded:
            return True
        if not self._discover():
            return False
        assert self.installation is not None
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        except ImportError as exc:  # pragma: no cover - dependency gating for the runtime env.
            self.last_error = "Transformers dependencies are missing. Install the project requirements and ensure torch is available."
            logger.warning("local_ai_requirements_missing", exc_info=exc)
            return False

        model_dir = self.installation.model
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
            torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            model = AutoModelForCausalLM.from_pretrained(
                str(model_dir),
                local_files_only=True,
                torch_dtype=torch_dtype,
                low_cpu_mem_usage=torch.cuda.is_available() is False,
            )
            if torch.cuda.is_available():
                self.pipeline = pipeline(
                    "text-generation",
                    model=model,
                    tokenizer=tokenizer,
                    device_map="auto",
                )
            else:
                self.pipeline = pipeline("text-generation", model=model, tokenizer=tokenizer)
            self.model_loaded = True
            self.last_error = ""
            logger.info("local_ai_model_loaded model=%s", model_dir)
            return True
        except Exception as exc:  # pragma: no cover - depends on the local model files and environment.
            self.pipeline = None
            self.model_loaded = False
            self.last_error = f"The local Gemma model could not be loaded: {exc}"
            logger.warning("local_ai_model_load_failed model=%s", model_dir, exc_info=exc)
            return False

    async def start_server(self) -> bool:
        """Load the local Gemma model once and keep it reusable."""
        if not self.config.local_ai_enabled:
            self.last_error = "Local AI is disabled."
            return False
        async with self._start_lock:
            if self.pipeline is not None and self.model_loaded:
                return True
            if not self._discover():
                return False
            if inspect.iscoroutinefunction(self._load_pipeline):
                result = await self._load_pipeline()
            else:
                result = await asyncio.to_thread(self._load_pipeline)
            return bool(result)

    async def health_check(self) -> bool:
        return self.config.local_ai_enabled and self.model_loaded and self.pipeline is not None and self._installation_is_present()

    async def is_available(self) -> bool:
        if await self.health_check():
            return True
        return await self.start_server()

    def _build_generation_prompt(self, prompt: str, system: str) -> str:
        tokenizer = getattr(self.pipeline, "tokenizer", None)
        if tokenizer is not None and hasattr(tokenizer, "apply_chat_template"):
            messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            try:
                return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except TypeError:
                pass
        return f"System: {system}\nUser: {prompt}\nAssistant:"

    def _generate_text(self, prompt: str, system: str) -> str:
        if self.pipeline is None:
            raise LocalAIError(self.last_error or "Local AI is unavailable.")
        prompt_text = self._build_generation_prompt(prompt, system)
        outputs = self.pipeline(
            prompt_text,
            max_new_tokens=min(256, max(64, int(self.config.local_ai_context_tokens / 8))),
            do_sample=False,
            pad_token_id=self.pipeline.tokenizer.eos_token_id,
            eos_token_id=self.pipeline.tokenizer.eos_token_id,
            return_full_text=False,
        )
        generated = ""
        if isinstance(outputs, list) and outputs:
            first = outputs[0]
            if isinstance(first, dict):
                generated = str(first.get("generated_text", "") or "")
            elif isinstance(first, str):
                generated = first
        elif isinstance(outputs, dict):
            generated = str(outputs.get("generated_text", "") or "")
        if "Assistant:" in generated and "Assistant:" in prompt_text:
            generated = generated.split("Assistant:", 1)[-1].strip()
        if "User:" in generated and "Assistant:" not in generated:
            generated = generated.split("User:", 1)[-1].strip()
        generated = generated.strip()
        if not generated:
            raise LocalAIError("Local AI returned an empty response.")
        return generated

    async def generate(self, prompt: str, system: str) -> str:
        """Run one inference request against the local Gemma model."""
        async with self._inference_lock:
            if not await self.is_available():
                raise LocalAIError(self.last_error or "Local AI is unavailable.")
            try:
                return await asyncio.to_thread(self._generate_text, prompt, system)
            except LocalAIError:
                raise
            except Exception as exc:  # pragma: no cover - handles runtime generation errors.
                self.last_error = f"Local AI inference failed: {exc}"
                raise LocalAIError(self.last_error) from exc

    async def stop_server(self) -> None:
        """Reset the in-memory pipeline when the app lifecycle ends."""
        self.pipeline = None
        self.model_loaded = False

    async def get_status(self) -> dict[str, Any]:
        """Return browser-safe local AI status without filesystem paths."""
        connected = self.model_loaded and self.pipeline is not None and self.config.local_ai_enabled
        if connected:
            self.last_error = ""
        return {
            "enabled": self.config.local_ai_enabled,
            "connected": connected,
            "status": "ready" if connected else ("starting" if self.config.local_ai_enabled else "offline"),
            "model": self.installation.model_name if self.installation else (getattr(self.config, "local_ai_model_name", "") or MODEL_NAME),
            "runtime": "transformers",
            "server_running": connected,
            "host": self.config.local_ai_host,
            "port": self.actual_port,
            "message": "" if connected else self.last_error,
        }