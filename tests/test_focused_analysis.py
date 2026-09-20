from types import SimpleNamespace

from backend.focused_analysis import build_excerpt, enrich_focused_result


def repository():
    return SimpleNamespace(
        owner="acme",
        name="app",
        url="https://github.com/acme/app",
        description="Demo repository",
        ref="main",
    )


def scan():
    return {
        "file_count": 3,
        "directory_count": 1,
        "total_size": 2048,
        "languages": {"Python": 2},
        "frameworks": ["FastAPI"],
        "top_level": ["src", "README.md"],
        "important_files": ["src/auth.py"],
    }


def test_build_excerpt_locates_symbol_and_redacts():
    source = "import os\n\nAPI_KEY = \"super-secret\"\n\ndef verify_token(token):\n    return token\n"
    lines, excerpt = build_excerpt(source, ["verify_token"])
    assert lines == "2-6"
    assert "def verify_token" in excerpt
    assert "super-secret" not in excerpt
    assert "[REDACTED]" in excerpt


def test_build_excerpt_falls_back_to_file_head():
    lines, excerpt = build_excerpt("\n".join(f"line{i}" for i in range(1, 60)), ["missing_symbol"])
    assert lines == "1-32"
    assert excerpt.startswith("line1")


def test_enrich_keeps_only_verifiable_paths():
    evidence = [{"path": "src/auth.py", "content": "def verify_token(token):\n    return token\n"}]
    result = {
        "answer": "Yes",
        "evidence": [
            {"file": "src/auth.py", "symbols": ["verify_token"], "reason": "defines it"},
            {"file": "docs/hallucinated.md", "symbols": [], "reason": "made up"},
        ],
    }
    enriched = enrich_focused_result(result, repository(), scan(), evidence)
    assert [item["file"] for item in enriched["evidence"]] == ["src/auth.py"]
    assert enriched["evidence"][0]["lines"] == "1-2"
    assert "def verify_token" in enriched["evidence"][0]["excerpt"]


def test_enrich_matches_nested_paths_by_suffix():
    evidence = [{"path": "backend/app/auth.py", "content": "class Authenticator:\n    pass\n"}]
    result = {"answer": "Yes", "evidence": [{"file": "app/auth.py", "symbols": ["Authenticator"], "reason": "class"}]}
    enriched = enrich_focused_result(result, repository(), scan(), evidence)
    assert enriched["evidence"][0]["file"] == "app/auth.py"
    assert "class Authenticator" in enriched["evidence"][0]["excerpt"]


def test_enrich_falls_back_to_real_evidence_when_nothing_matches():
    evidence = [
        {"path": "src/auth.py", "content": "def login():\n    pass\n"},
        {"path": "src/db.py", "content": "def connect():\n    pass\n"},
    ]
    result = {"answer": "Unsure", "evidence": [{"file": "nowhere.py", "symbols": [], "reason": "guess"}]}
    enriched = enrich_focused_result(result, repository(), scan(), evidence)
    assert [item["file"] for item in enriched["evidence"]] == ["src/auth.py", "src/db.py"]
    assert all(item["excerpt"] for item in enriched["evidence"])


def test_enrich_attaches_repository_and_structure():
    enriched = enrich_focused_result({"answer": "Yes", "evidence": []}, repository(), scan(), [])
    assert enriched["repository"]["owner"] == "acme"
    assert enriched["repository"]["ref"] == "main"
    assert enriched["structure"]["file_count"] == 3
    assert enriched["structure"]["languages"] == {"Python": 2}
    assert enriched["evidence"] == []
