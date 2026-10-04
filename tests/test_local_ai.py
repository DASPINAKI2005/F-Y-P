import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.local_ai import LocalAIClient, LocalAIError, discover_installation


def make_local_model(root: Path, name: str = "gemma-3-1b-it") -> Path:
    model_dir = root / "models" / name
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text('{"model_type": "gemma3", "architectures": ["Gemma3ForCausalLM"]}', encoding="utf-8")
    (model_dir / "tokenizer_config.json").write_text('{"tokenizer_class": "AutoTokenizer"}', encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"")
    return model_dir


def test_project_local_model_is_discovered(tmp_path, monkeypatch):
    project_root = tmp_path
    monkeypatch.setattr("backend.local_ai._project_root", lambda: project_root)
    model_dir = project_root / "models" / "gemma-3-1b-it"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text('{"model_type": "gemma3"}', encoding="utf-8")
    (model_dir / "tokenizer_config.json").write_text('{"tokenizer_class": "AutoTokenizer"}', encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"")
    installation = discover_installation(project_root)
    assert installation is not None
    assert installation.model == model_dir
    assert installation.model_name == "google/gemma-3-1b-it"


def test_missing_local_model_is_rejected(tmp_path):
    project_root = tmp_path / "project"
    assert discover_installation(project_root) is None


def test_metadata_only_model_directory_is_rejected(tmp_path):
    model_dir = make_local_model(tmp_path)
    (model_dir / "tokenizer.json").unlink()
    (model_dir / "model.safetensors").unlink()

    assert discover_installation(model_dir) is None


def test_local_inference_uses_project_model_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    model_dir = make_local_model(project_root)
    config = SimpleNamespace(
        local_ai_enabled=True,
        local_ai_host="127.0.0.1",
        local_ai_port=8080,
        local_ai_timeout=30,
        local_ai_startup_timeout=10,
        local_ai_context_tokens=4096,
        local_ai_max_context_chars=30000,
        local_ai_max_files=8,
        local_ai_max_file_chars=4000,
        local_ai_model_name="google/gemma-3-1b-it",
        local_ai_model_dir=str(model_dir),
    )
    client = LocalAIClient(config)

    async def fake_load(self):
        self.pipeline = SimpleNamespace()
        self.model_loaded = True
        self.last_error = ""
        return True

    monkeypatch.setattr(LocalAIClient, "_load_pipeline", fake_load)
    assert asyncio.run(client.start_server())
    assert client.installation is not None
    assert client.installation.model == model_dir


def test_inference_failure_reports_missing_model_cleanly(tmp_path):
    config = SimpleNamespace(
        local_ai_enabled=True,
        local_ai_host="127.0.0.1",
        local_ai_port=8080,
        local_ai_timeout=30,
        local_ai_startup_timeout=10,
        local_ai_context_tokens=4096,
        local_ai_max_context_chars=30000,
        local_ai_max_files=8,
        local_ai_max_file_chars=4000,
        local_ai_model_name="google/gemma-3-1b-it",
        local_ai_model_dir=str(tmp_path / "missing-model"),
    )
    client = LocalAIClient(config)
    with pytest.raises(LocalAIError, match="gemma-3-1b-it|download"):
        asyncio.run(client.generate("summarize", "system"))


def test_status_uses_local_model_metadata():
    config = SimpleNamespace(
        local_ai_enabled=True,
        local_ai_host="127.0.0.1",
        local_ai_port=8080,
        local_ai_timeout=30,
        local_ai_startup_timeout=10,
        local_ai_context_tokens=4096,
        local_ai_max_context_chars=30000,
        local_ai_max_files=8,
        local_ai_max_file_chars=4000,
        local_ai_model_name="google/gemma-3-1b-it",
        local_ai_model_dir="models/gemma-3-1b-it",
    )
    client = LocalAIClient(config)
    client.installation = SimpleNamespace(model_name="google/gemma-3-1b-it", model=Path("models/gemma-3-1b-it"), exists=lambda: True)
    status = asyncio.run(client.get_status())
    assert status["model"] == "google/gemma-3-1b-it"
    assert status["runtime"] == "transformers"
