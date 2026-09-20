import io
import json
import tarfile
from pathlib import Path

import pytest

from backend.ai_router import parse_result
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


def test_frontend_uses_safe_dom_apis():
    source = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "textContent" in source