# GitHub Repo Analyzer

A local-first FastAPI application for understanding public GitHub repositories through safe static analysis and automatic AI provider fallback.

## Features

- Public GitHub URL validation and REST archive downloads; Git is not required.
- Zip-slip/path traversal protection, archive member/extraction/file/prompt limits, ignored binary/vendor paths, and common secret redaction.
- Technology and framework detection, repository structure inventory, important-file ranking, and staged evidence prompts.
- Provider-neutral adapters for Gemini, Groq, OpenRouter, and Hugging Face with automatic fallback and normalized JSON validation.
- SQLite history with status, score, summary, provider, and full normalized report.
- Responsive vanilla HTML/CSS/JavaScript interface served by FastAPI.

## Run locally

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies: `python -m pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and configure at least one AI provider key.
5. Start the app: `python run.py`
6. Open http://127.0.0.1:8000.

A GitHub token is optional for public repositories, but useful for higher API limits. Keys are backend-only and never sent to the browser.

## Advanced analysis

Alongside the standard repository report, the analyzer can answer one specific question about a repository. Enable **Advanced analysis**, choose a repository type, and ask a question such as *"Where is authentication implemented?"*.

Focused runs add two stages: candidate files are ranked against the concepts in your question, then the model must answer using only that evidence. Every citation is re-opened afterwards, the real excerpt and line range are extracted from the file that exists on disk, and citations that cannot be verified are discarded. Answers are labelled `implemented`, `partial`, `referenced_only`, `not_found`, or `uncertain`, and rated `strong`, `moderate`, `weak`, or `insufficient`.

Applying the selected repository type requires a question; the type only guides ranking and interpretation.

## Architecture

`backend/main.py` owns HTTP endpoints and the bounded background analysis lifecycle. `github_service.py` handles GitHub acquisition. `repo_parser.py` performs static scanning without executing repository content. `prompt_builder.py` creates UTF-8 byte-bounded evidence context. `ai_router.py` contains independent provider adapters and fallback routing. `database.py` stores metadata and results in SQLite. Development data lives in `db/`; frozen PyInstaller builds use a persistent per-user `GitHubRepoAnalyzer` data directory (`%APPDATA%` on Windows).

## AI fallback

Providers are attempted in this order: Gemini, Groq, OpenRouter, Hugging Face. Unconfigured providers are skipped. HTTP rate limits, transient failures, network errors, empty output, malformed JSON, and schema failures advance to the next configured provider. Raw keys and authorization headers are never logged.

## Security model

Repositories are untrusted data. The application never runs source code, package managers, Makefiles, Dockerfiles, workflows, or setup scripts. Archive members are resolved under a deterministic workspace and rejected if they escape it. Files are bounded and filtered before selected source context is transmitted to an AI provider. Repository text is explicitly framed as evidence, not instructions, to reduce prompt injection risk.

## Packaging

The application has no Node.js, Git, Docker, database server, or system package-manager runtime requirement. A Windows launcher can run `python run.py`; standalone executables can be produced with PyInstaller using the included `packaging.spec` after installing `pyinstaller` in a build environment.

## Tests

Run `python -m pytest tests -q`. The tests cover URL parsing, traversal protection, archive extraction, importance ranking, deterministic workspaces, focused-analysis evidence enrichment, and SQLite persistence. Live provider and GitHub calls are intentionally not part of the unit suite.

Pass the `tests` path explicitly: a bare `python -m pytest -q` also collects example projects under `db/workspaces/`, which are downloaded repositories and not part of the test suite.

## Limitations and future work

The MVP uses GitHub REST for metadata/archive acquisition; GraphQL and Code Search are intentionally optional extension points rather than mandatory calls. It does not execute code or provide account management. Successful workspaces are retained as local cache; failed workspaces are removed, and deleting an analysis removes its deterministic workspace. On restart, interrupted non-terminal jobs are marked failed rather than polled forever. The application remains local-only by default and binds to `127.0.0.1`.
