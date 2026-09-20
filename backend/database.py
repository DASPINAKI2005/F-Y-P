import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS analyses (
 id TEXT PRIMARY KEY, repository_url TEXT NOT NULL, owner TEXT NOT NULL, name TEXT NOT NULL,
 ref TEXT, status TEXT NOT NULL, score INTEGER, summary TEXT, provider TEXT,
 analysis_mode TEXT NOT NULL DEFAULT 'standard', repository_type TEXT, user_question TEXT,
 result_json TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

def _column_names(connection: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in connection.execute("PRAGMA table_info(analyses)").fetchall()}

def _migrate(connection: sqlite3.Connection) -> None:
    existing = _column_names(connection)
    additions = {
        "analysis_mode": "TEXT NOT NULL DEFAULT 'standard'",
        "repository_type": "TEXT",
        "user_question": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE analyses ADD COLUMN {name} {ddl}")

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def init_db() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        _migrate(db)
        if db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            db.execute("INSERT INTO schema_version(version) VALUES (1)")
        db.execute("UPDATE analyses SET status = 'failed', error = ?, updated_at = ? WHERE status NOT IN ('completed', 'failed')", ("Analysis interrupted because the application restarted.", now()))

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_analysis(analysis_id: str, repository_url: str, owner: str, name: str, ref: str | None, analysis_mode: str = "standard", repository_type: str | None = None, user_question: str | None = None) -> None:
    timestamp = now()
    with connect() as db:
        db.execute("INSERT INTO analyses(id, repository_url, owner, name, ref, status, analysis_mode, repository_type, user_question, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (analysis_id, repository_url, owner, name, ref, "queued", analysis_mode, repository_type, user_question, timestamp, timestamp))

def update_analysis(analysis_id: str, **fields: Any) -> None:
    fields["updated_at"] = now()
    clause = ", ".join(f"{key} = ?" for key in fields)
    with connect() as db:
        db.execute(f"UPDATE analyses SET {clause} WHERE id = ?", (*fields.values(), analysis_id))

def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    raw_result = result.pop("result_json")
    if raw_result:
        try:
            result["result"] = json.loads(raw_result)
        except (TypeError, ValueError):
            result["result"] = None
            result["error"] = result.get("error") or "Stored analysis result is invalid."
    else:
        result["result"] = None
    return result

def list_analyses() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM analyses ORDER BY created_at DESC").fetchall()
    analyses = []
    for row in rows:
        result = dict(row)
        raw_result = result.pop("result_json")
        if raw_result:
            try:
                result["result"] = json.loads(raw_result)
            except (TypeError, ValueError):
                result["result"] = None
                result["error"] = result.get("error") or "Stored analysis result is invalid."
        else:
            result["result"] = None
        analyses.append(result)
    return analyses

def delete_analysis(analysis_id: str) -> bool:
    with connect() as db:
        cursor = db.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    return cursor.rowcount > 0
