from backend.database import create_analysis, get_analysis, init_db, update_analysis

def test_sqlite_persistence(tmp_path, monkeypatch):
    import backend.database as database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "analyzer.db")
    init_db()
    create_analysis("abc", "https://github.com/a/b", "a", "b", None)
    update_analysis("abc", status="completed", score=88, result_json='{"overall_score": 88}')
    saved = get_analysis("abc")
    assert saved["status"] == "completed"
    assert saved["result"]["overall_score"] == 88
