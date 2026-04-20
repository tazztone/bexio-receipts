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
    the recommended "Human-in-the-loop" production workflow.
  - If `true`: Receipts that pass validation are pushed automatically. Use this
    only if you fully trust your extraction results.
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
  to `8.1`.
- **`DEFAULT_PAYMENT_TERMS_DAYS`**: Number of days for payment terms. Defaults
  to `30`.

## OCR & Extraction Strategy

The system supports two OCR engines and multiple LLM providers.

### OCR Engine (`GLM-OCR`)

The system uses **GLM-OCR** as its primary OCR engine. It is a multimodal
LLM-based engine that runs locally via Ollama. It is highly effective for
complex VAT layouts and low-quality scans.

| Variable | Description | Default |
|---|---|---|
| `GLM_OCR_URL` | URL for the Ollama instance running GLM-OCR | `http://localhost:11434` |
| `GLM_OCR_MODEL` | Model name for GLM-OCR in Ollama | `glm-ocr` |

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
> `GLM_OCR_URL` and `OLLAMA_URL` are separate. This allows you to run the heavy
> OCR model on one host (e.g., with a GPU) and the extraction LLM on another
> (e.g., a standard CPU host).

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
