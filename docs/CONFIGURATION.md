# Configuration Guide

bexio-receipts is configured primarily through environment variables. You can
set these in a `.env` file in the root of the repository.

## ⚡ Interactive Setup (Recommended)
The easiest way to configure the system is to run the interactive setup command:
```bash
uv run bexio-receipts init
```
This command will guide you through the most important settings and
automatically create a `.env` file for you.

## Core API Settings

- **`ENV`**: Set to `production` to enable strict security checks (e.g.,
  rejecting weak default passwords). Defaults to `development`.
- **`OFFLINE_MODE`**: Set to `true` to run the UI and LLM/OCR pipeline locally
  without connecting to Bexio. Defaults to `false`.
- **`BEXIO_API_TOKEN`**: Your bexio Personal Access Token. Create this in
  bexio under *Settings > All Settings > Apps & API > API Keys*. Required
  unless `OFFLINE_MODE=true`.
- **`BEXIO_BASE_URL`**: Defaults to `https://api.bexio.com`.
- **`BEXIO_PUSH_ENABLED`**: Write-gate for the pipeline.
  - If `false` (default): All receipts go to the **Review Dashboard**. This is
    the mandatory "Human-in-the-loop" production workflow for all ingestion 
    sources, including the local Folder Watcher and Google Drive.
  - If `true`: Receipts that pass validation are pushed automatically.
- **`DEFAULT_BOOKING_ACCOUNT_ID`**: (Required) Default bexio account ID for new
  expenses (e.g., `630`).
- **`DEFAULT_BANK_ACCOUNT_ID`**: (Required) Default bexio bank account ID for
  payments (e.g., `1`).
- **`BEXIO_ACCOUNTS`**: A dictionary mapping account numbers to descriptions
  (e.g., `{"4200": "Einkauf Handelsware", "4400": "Dienstleistung"}`). Used by
  the Step 3 classifier to assign accounts based on product context.
- **`BEXIO_ALLOWED_SOLL_ACCOUNTS`**: Comma-separated list of account *numbers*
  (e.g., `4200,4400`) allowed in the review UI dropdown.
- **`BEXIO_HABEN_ACCOUNT_BANK`**: Account *number* used for the "Bank" payment
  toggle (e.g., `1020`).
- **`BEXIO_HABEN_ACCOUNT_CASH`**: Account *number* used for the "Cash" payment
  toggle (e.g., `1000`).
- **`DEFAULT_VAT_RATE`**: Default Swiss VAT rate (8.1, 2.6, or 3.8). Defaults
  to `8.1`. The pipeline also supports legacy rates (7.7 and 2.5).
- **`DEFAULT_PAYMENT_TERMS_DAYS`**: Number of days for payment terms. Defaults
  to `30`.

## OCR & Extraction Strategy

The system supports two primary processing modes: **Vision** (New, high-fidelity) and **OCR** (Legacy fallback).

### Processor Mode (`PROCESSOR_MODE`)
- **`vision`** (Default): Uses a single multimodal call to **Qwen3.6-35B-A3B**. Recommended for best accuracy on complex layouts (e.g., wholesalers like Aligro/Prodega).
- **`ocr`**: Uses the legacy pipeline (**GLM-OCR SDK** + 3-step LLM extraction). Useful for low-VRAM environments or as a fallback.

| Variable | Description | Default |
|---|---|---|
| `PROCESSOR_MODE` | `vision` or `ocr` | `vision` |

### Vision Pipeline (`vision`)
When `PROCESSOR_MODE=vision`, the system uses a high-performance VLM backend.

| Variable | Description | Default |
|---|---|---|
| `VISION_MODEL` | HuggingFace model path | `tclf90/Qwen3.6-35B-A3B-AWQ` |
| `VISION_API_HOST` | Hostname for the vLLM server | `localhost` |
| `VISION_API_PORT` | Port for the vLLM server | `8000` |
| `VISION_MANAGE_SERVER` | Start/stop vLLM automatically | `true` |
| `VISION_GPU_MEMORY_UTILIZATION` | Fraction of VRAM to reserve | `0.9` |
| `VISION_TENSOR_PARALLEL_SIZE` | GPUs/Shards for TP (e.g. 4 for RTX 3090) | `4` |
| `VISION_MAX_MODEL_LEN` | Context window size | `32768` |
| `VISION_QUANTIZATION` | Weights format | `awq` |

### Legacy OCR Engine (`ocr`)
Used when `PROCESSOR_MODE=ocr`. Connects to a vLLM backend running GLM-OCR.

| Variable | Description | Default |
|---|---|---|
| `GLM_OCR_API_HOST` | Hostname of the vLLM backend | `localhost` |
| `GLM_OCR_API_PORT` | Port of the vLLM backend | `8080` |
| `GLM_OCR_LAYOUT_DEVICE` | Device for layout analysis (`cpu`, `cuda`) | `cpu` |
| `GLM_OCR_TIMEOUT` | Seconds for the entire OCR stage | `300` |
| `GLM_OCR_CONNECT_TIMEOUT` | Seconds for connection establishment | `60` |
| `GLM_OCR_REQUEST_TIMEOUT` | Seconds for request fulfillment | `300` |
| `GLM_OCR_MAX_TOKENS` | Maximum tokens for the layout model | `2048` |

#### Managed vLLM Server Settings (Legacy)
If `GLM_OCR_MANAGE_SERVER=true`, the app will launch the GLM vLLM server automatically.

| Variable | Description | Default |
|---|---|---|
| `GLM_OCR_MANAGE_SERVER` | Start/stop vLLM automatically | `true` |
| `GLM_OCR_VLLM_GPU_MEMORY_UTILIZATION` | Fraction of VRAM to reserve | `0.2` |
| `GLM_OCR_VLLM_MAX_MODEL_LEN` | Context window for vLLM | `8192` |

<!-- prettier-ignore -->
> [!TIP]
> The system automatically uses a **Three-Step Extraction** process:
> 1. **Searcher**: Transcribes raw data and locates the VAT table.
> 2. **VAT Assigner**: Parses the VAT snippet with math validation.
> 3. **Account Classifier**: Assigns booking accounts based on product context.


### LLM Providers (`LLM_PROVIDER`)
- **`ollama`** (Default): For local, privacy-first extraction. Requires an
  Ollama instance.
- **`openai`**: For high-performance cloud extraction. Requires `OPENAI_API_KEY`.

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `ollama` or `openai` | `ollama` |
| `LLM_MODEL` | The specific LLM model to use | `qwen3.5:9b` |
| `OLLAMA_URL` | URL for the Ollama instance | `http://localhost:11434` |
| `OPENAI_API_KEY` | Your OpenAI API key (if using `openai`) | `None` |

<!-- prettier-ignore -->
> [!NOTE]
> `GLM_OCR_API_HOST` and `OLLAMA_URL` are separate. This allows you to run the 
> heavy layout/vision model on one host (e.g., with a GPU) and the extraction 
> LLM on another (e.g., a standard CPU host).

## Ingestion Sources

Each ingestion source has its own configuration block.

| Variable | Description | Default |
|---|---|---|
| `INBOX_PATH` | Local folder to watch for files | `./inbox` |
| `MAX_RECEIPT_AGE_DAYS` | Skip receipts older than this | `365` |
| `DATABASE_PATH` | Path to SQLite database | `processed_receipts.db` |


### Google Drive Integration
- **`GDRIVE_CREDENTIALS_FILE`**: Path to `service_account.json` (recommended)
  or OAuth `credentials.json`.
- **`GDRIVE_TOKEN_PATH`**: Path where OAuth2 tokens are stored. Defaults to
  `token.json`.
- **`GDRIVE_FOLDER_ID`**: The ID of the folder to poll.
- **`GDRIVE_PROCESSED_FOLDER_ID`**: Optional ID where files are moved after
  processing.
- **`GDRIVE_POLL_INTERVAL`**: Seconds between polls. Defaults to `60`.

## Security & Dashboard

<!-- prettier-ignore -->
> [!WARNING]
> The default `REVIEW_USERNAME` and `REVIEW_PASSWORD` are both set to `admin`.
> **Change these immediately** if your dashboard is accessible over a network.
> If `ENV=production`, the application will refuse to start if the password
> is still set to the string `password`.

- **`SECRET_KEY`**: A secure random string used for session security. Change
  this in production.
- **`REVIEW_USERNAME`**: Username for accessing the Review Dashboard. Defaults
  to `admin`.
- **`REVIEW_PASSWORD`**: Password for accessing the Review Dashboard. Defaults
  to `admin`.
- **`REVIEW_USERS`**: Multi-user support JSON string `{"username": "password"}`.
  If set, this overrides the single user/password settings.
- **`REVIEW_DIR`**: Where files waiting for manual approval are stored.
  Defaults to `./review_queue`.
