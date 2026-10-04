#!/usr/bin/env python3
"""Download the project-local Gemma 3 1B IT model into models/gemma-3-1b-it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "gemma-3-1b-it"
MODEL_ID = "google/gemma-3-1b-it"


def _is_model_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    has_metadata = (path / "config.json").exists() and (path / "tokenizer_config.json").exists()
    has_weights = any(path.glob("*.safetensors")) or any(path.glob("pytorch_model*.bin"))
    has_tokenizer = any(
        (path / filename).exists()
        for filename in ("tokenizer.json", "tokenizer.model", "spiece.model")
    )
    return has_metadata and has_weights and has_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the project-local Gemma 3 1B IT model.")
    parser.add_argument("--target", type=Path, default=DEFAULT_MODEL_DIR, help="Directory to store the model in.")
    parser.add_argument("--force", action="store_true", help="Redownload even if the model directory already looks populated.")
    args = parser.parse_args()

    target_dir = args.target.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if _is_model_dir(target_dir) and not args.force:
        print(f"Model already present at {target_dir}")
        return 0

    print(f"Downloading {MODEL_ID} to {target_dir}...")
    try:
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
        )
    except Exception as exc:  # pragma: no cover - exercised by the runtime environment.
        print(f"Model download failed: {exc}", file=sys.stderr)
        print("Ensure you have internet access and, if needed, a valid HF_TOKEN environment variable for gated access.", file=sys.stderr)
        return 1

    if not _is_model_dir(target_dir):
        print(f"Download completed, but no model files were found in {target_dir}.", file=sys.stderr)
        return 1

    print(f"Model ready at {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
