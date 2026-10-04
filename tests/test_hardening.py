import asyncio
import io
import json
import tarfile
from pathlib import Path

import pytest

from types import SimpleNamespace

from backend.ai_router import build_repo_fallback_report, parse_result
from backend.database import create_analysis, get_analysis, init_db, list_analyses
from backend.prompt_builder import limit_prompt_bytes
from backend.repo_parser import extract_archive, read_selected


def valid_result(score):
    return json.dumps({"repository": {}, "executive_summary": "ok", "technology_stack": [], "overall_score": score, "limitations": []})


@pytest.mark.parametrize("value", ["ascii", "বাংলা" * 100, "🙂" * 100, "mixed বাংলা🙂" * 100])
def test_prompt_limit_is_utf8_byte_safe(value):
    prompt = limit_prompt_bytes(value, 37)
    assert len(prompt.encode("utf-8")) <= 37
    prompt.encode("utf-8").decode("utf-8")


@pytest.mark.parametrize("score, expected", [("88.5", 88), (88.5, 88), (-4, 0), (140, 100)])
def test_parse_result_normalizes_score(score, expected):
    assert parse_result(valid_result(score))["overall_score"] == expected


@pytest.mark.parametrize("score", [None, "not-a-score", float("inf"), True])
def test_parse_result_rejects_invalid_score(score):
    with pytest.raises(Exception):
        parse_result(valid_result(score))


def test_archive_member_limit_and_partial_cleanup(tmp_path, monkeypatch):
    import backend.repo_parser as parser
    monkeypatch.setattr(parser.settings, "max_archive_members", 2)
    archive = tmp_path / "many.tar"
    with tarfile.open(archive, "w") as output:
        for name in ("root/a", "root/b", "root/c"):
            info = tarfile.TarInfo(name)
            info.size = 1
            output.addfile(info, io.BytesIO(b"x"))
    workspace = tmp_path / "workspace"
    with pytest.raises(ValueError, match="too many"):
        extract_archive(archive, workspace)
    assert not workspace.exists()


def test_secret_redaction_handles_common_assignments(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "config.py"
    source.write_text('API_KEY = "real-value"\npassword: real-password\nprint("harmless")\n', encoding="utf-8")
    selected = read_selected(root, ["config.py"])
    assert "real-value" not in selected[0]["content"]
    assert "real-password" not in selected[0]["content"]
    assert 'print("harmless")' in selected[0]["content"]


def test_corrupt_history_result_isolated(tmp_path, monkeypatch):
    import backend.database as database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "analyzer.db")
    init_db()
    create_analysis("bad", "https://github.com/a/b", "a", "b", None)
    database.update_analysis("bad", result_json="{not json")
    assert get_analysis("bad")["result"] is None
    assert len(list_analyses()) == 1


def test_partial_json_is_normalized_with_repository_fallback():
    payload = json.dumps({
        "repository": {"name": "demo", "owner": "acme", "url": "https://github.com/acme/demo", "description": "Demo app"},
        "overall_score": 80,
        "technology_stack": ["FastAPI", "Python"],
        "limitations": ["Limited evidence"]
    })
    result = parse_result(payload)
    assert result["executive_summary"]
    assert result["strengths"]
    assert result["weaknesses"]
    assert 0 <= result["overall_score"] <= 100
    assert result["repository"]["name"] == "demo"


def test_parse_result_accepts_realistic_local_model_outputs():
    payload = '''Here is the analysis:
```json
{
  "summary": "Project uses {FastAPI} and \\\"good\\\" docs.",
  "weaknesses": ["Missing coverage"],
  "details": [{"path": "app/main.py", "reason": "Core logic"}],
  "improvements": ["Add tests"]
}
```
Hope this helps.'''
    result = parse_result(payload)
    assert result["executive_summary"] == 'Project uses {FastAPI} and "good" docs.'
    assert result["weaknesses"] == ["Missing coverage"]
    assert result["strengths"]


def test_parse_result_rejects_empty_and_invalid_model_output():
    with pytest.raises(Exception, match="empty response|valid JSON|malformed JSON"):
        parse_result("   \n\t  ")
    with pytest.raises(Exception, match="valid JSON|malformed JSON"):
        parse_result("Random prose without any JSON object.")


def test_generate_analysis_retries_once_and_uses_local_success():
    from backend.ai_router import generate_analysis

    calls = []

    async def fake_generate(prompt, system):
        calls.append((prompt, system))
        if len(calls) == 1:
            return '```json\n{"summary": "bad value", "weaknesses": []\n```'
        return json.dumps({
            "repository": {"name": "demo", "owner": "acme", "url": "https://github.com/acme/demo", "description": "Demo app"},
            "summary": "OK summary",
            "weaknesses": ["Minor issue"],
            "overall_score": 91,
            "limitations": []
        })

    import backend.ai_router as ai_router
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ai_router.local_ai, "generate", fake_generate)
    try:
        result, provider = asyncio.run(generate_analysis("prompt", "system", repository=SimpleNamespace(name="demo", owner="acme", url="https://github.com/acme/demo", description="Demo app"), scan={}, selected=[]))
    finally:
        monkeypatch.undo()
    assert provider == "Local AI"
    assert len(calls) == 2
    assert result["summary"] == "OK summary"
    assert result["overall_score"] == 91


def test_generate_analysis_falls_back_when_local_model_keeps_failing():
    from backend.ai_router import generate_analysis

    async def fake_generate(prompt, system):
        return "This is not JSON at all."

    import backend.ai_router as ai_router
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ai_router.local_ai, "generate", fake_generate)
    try:
        result, provider = asyncio.run(generate_analysis("prompt", "system", repository=SimpleNamespace(name="demo", owner="acme", url="https://github.com/acme/demo", description="Demo app"), scan={}, selected=[]))
    finally:
        monkeypatch.undo()
    assert provider == "Local AI fallback"
    assert result["executive_summary"]
    assert result["weaknesses"]


def test_frontend_uses_safe_dom_apis():
    source = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "textContent" in source