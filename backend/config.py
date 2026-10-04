import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "google/gemma-3-1b-it"
MODEL_DIR = ROOT / "models" / "gemma-3-1b-it"


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
    github_token: str = ""
    local_ai_enabled: bool = True
    local_ai_host: str = "127.0.0.1"
    local_ai_port: int = 8080
    local_ai_timeout: int = 180
    local_ai_startup_timeout: int = 60
    local_ai_context_tokens: int = 8192
    local_ai_max_context_chars: int = 30000
    local_ai_max_files: int = 8
    local_ai_max_file_chars: int = 4000
    local_ai_model_name: str = MODEL_NAME
    local_ai_model_dir: str = str(MODEL_DIR)
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
