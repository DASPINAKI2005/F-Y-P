# GitHub Repo Analyzer

A local-first FastAPI application for safe GitHub repository analysis using a project-local Gemma model and source-backed review.

## AI model

- Model: Google Gemma 3 1B IT
- Model ID: `google/gemma-3-1b-it`
- Inference: Local

## Architecture

```text
GitHub Repository
      ↓
Safe Repository Acquisition
      ↓
Static Analysis
      ↓
Relevant Code / Context
      ↓
Local Gemma 3 1B IT
      ↓
Analysis Result
      ↓
Existing Application UI
```

The analysis pipeline acquires a repository archive, inspects it safely without executing code, ranks the most relevant files, and then sends a bounded prompt to the local Gemma model for reasoning.

## Local model location

```text
models/gemma-3-1b-it/
```

This is the canonical local checkout directory for the project. The app resolves the model from this location and does not depend on any external removable drive.

## Setup

1. Clone the repository.
2. Create or activate a Python virtual environment.
3. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

4. Authenticate with Hugging Face if required by access policies for the model.
5. Accept the applicable Gemma terms and access requirements.
6. Download the model:

```bash
python scripts/download_model.py
```

7. Verify the local model exists under:

```text
models/gemma-3-1b-it/
```

8. Start the app:

```bash
python run.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Key components

- `backend/main.py` handles the FastAPI app and analysis lifecycle.
- `backend/github_service.py` validates GitHub URLs and downloads repository archives.
- `backend/repo_parser.py` performs safe static extraction and analysis.
- `backend/prompt_builder.py` assembles the evidence-backed prompt.
- `backend/local_ai.py` loads the local Gemma model from `models/gemma-3-1b-it`.
- `scripts/download_model.py` downloads the required model files to the local project directory.

## Security and safety

Repository content is treated as untrusted input. The app never executes project code from the repository, and extracted files are filtered and bounded before they are included in prompts.

## License and third-party notices

This repository includes third-party model notice documentation:

- `NOTICE`
- `docs/THIRD_PARTY_LICENSES.md`

Official Gemma documentation and terms:

- Google Gemma Terms of Use: https://ai.google.dev/gemma/terms
- Google Gemma Prohibited Use Policy: https://ai.google.dev/gemma/terms#prohibited-use-policy

Gemma is used under the applicable Gemma Terms of Use.

## Testing

Run the project test suite with:

```bash
python -m pytest tests -q
```

## Repository strategy

The project keeps the application source, model download script, and licensing notices in Git while leaving the downloaded model weights local to the machine under `models/gemma-3-1b-it/`.
