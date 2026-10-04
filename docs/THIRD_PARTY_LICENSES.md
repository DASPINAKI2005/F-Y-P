# Third-Party Licenses and Model Notices

## Google Gemma 3 1B IT

- Model provider: Google
- Model name: Gemma 3 1B IT
- Hugging Face model identifier: `google/gemma-3-1b-it`
- Official Gemma Terms of Use: https://ai.google.dev/gemma/terms
- Official Gemma Prohibited Use Policy: https://ai.google.dev/gemma/terms#prohibited-use-policy

This project uses Gemma for local repository analysis and summarization. The model is loaded from the local project directory `models/gemma-3-1b-it/` and is not executed through any external removable-drive flow.

### Purpose in this project

The model is used to reason over static repository evidence, assist with repository understanding, and help summarize analysis results. The model is not used to execute project code or to operate outside the repository analysis workflow.

### Local inference architecture

The application resolves the local model directory in the repository and loads it with the local Transformers runtime. The model is kept on the local machine and is not required to be stored on an external drive.

### Distribution and licensing

The project keeps the source code and model-download script in the repository, while the actual model weights are expected to be downloaded and stored locally under `models/gemma-3-1b-it/` on the user's machine. This repository does not claim to redistribute model weights or guarantee that a particular distribution path is permitted in all environments.

Users should review the applicable Google Gemma terms, platform requirements, and access restrictions before downloading, storing, or using the model. Gemma is used under the applicable Gemma Terms of Use.

This document is informational only and is not legal advice.
