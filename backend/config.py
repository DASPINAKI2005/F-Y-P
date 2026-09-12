import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

def _data_root() -> Path:
    if not getattr(sys, "frozen", False):
        return ROOT / "db"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "GitHubRepoAnalyzer"

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))

class Settings(BaseSettings):
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    hf_token: str = ""
    github_token: str = ""
    max_repository_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 150 * 1024 * 1024
    max_file_bytes: int = 120 * 1024
    max_prompt_bytes: int = 900 * 1024
    max_archive_members: int = 10000
    max_concurrent_analyses: int = 2
    max_pending_analyses: int = 8
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

settings = Settings()
DATA_ROOT = _data_root()
DB_PATH = DATA_ROOT / "analyzer.db"
WORKSPACE_ROOT = DATA_ROOT / "workspaces"
FRONTEND_ROOT = RESOURCE_ROOT / "frontend"
