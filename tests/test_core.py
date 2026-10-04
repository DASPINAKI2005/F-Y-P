import io
import tarfile
from pathlib import Path
from backend.ai_router import parse_result
import pytest
from backend.repo_parser import extract_archive, rank_important
from backend.security import parse_github_url, safe_join, workspace_for

def test_parse_github_url():
    assert parse_github_url("https://github.com/facebook/react") == {"owner": "facebook", "name": "react", "ref": ""}
    assert parse_github_url("https://github.com/org/app/tree/main")['ref'] == "main"
    with pytest.raises(ValueError):
        parse_github_url("https://gitlab.com/org/app")

def test_safe_join_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_join(tmp_path, "../../escape.txt")

def test_extract_archive_rejects_unsafe_member(tmp_path):
    archive = tmp_path / "repo.tar"
    with tarfile.open(archive, "w") as output:
        info = tarfile.TarInfo("root/../../escape.txt")
        info.size = 4
        output.addfile(info, io.BytesIO(b"bad!"))
    with pytest.raises(ValueError):
        extract_archive(archive, tmp_path / "workspace")

def test_importance_ranking():
    result = rank_important([{"path": "src/routes.py", "size": 10}, {"path": "README.md", "size": 10}], [])
    assert result[0] == "README.md"

def test_workspace_is_deterministic():
    assert workspace_for("a", "b", "main") == workspace_for("a", "b", "main")


def test_local_analysis_json_accepts_fences_and_prose_around_json():
    payload = '{"overall_score": 80}'
    assert parse_result(f"```json\n{payload}\n```")["overall_score"] == 80
    assert parse_result(f"{payload}\nHope this helps.")["overall_score"] == 80


def test_required_api_contract_remains_available():
    from backend.main import app

    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    expected = {
        ("/api/health", "GET"),
        ("/api/repositories/validate", "POST"),
        ("/api/analyze", "POST"),
        ("/api/analyze/{analysis_id}", "GET"),
        ("/api/analyses", "GET"),
        ("/api/analyses/{analysis_id}", "GET"),
        ("/api/analyses/{analysis_id}", "DELETE"),
        ("/api/settings/status", "GET"),
    }
    assert expected <= routes
    assert not any(path == "/api/settings/priority" for path, _method in routes)
