# Configuration Guide

`bexio-receipts` is configured primarily through environment variables. You can set these in a `.env` file in the root of the repository.

## ⚡ Interactive Setup (Recommended)
The easiest way to configure the system is to run the interactive setup command:
```bash
uv run bexio-receipts init
```
This command will guide you through the most important settings and automatically create a `.env` file for you.

## Core API Settings

- **`BEXIO_API_TOKEN`**: Your bexio Personal Access Token. Create this in bexio under *Settings > All Settings > Apps & API > API Keys*.
- **`BEXIO_BASE_URL`**: Defaults to `https://api.bexio.com`.

## OCR & Extraction Strategy

The system supports two OCR engines and multiple LLM providers.

### OCR Engines (`OCR_ENGINE`)
- **`paddleocr`**: Runs locally. Fast. Requires `paddlepaddle` and `paddleocr` Python packages.
- **`glm-ocr`** (Default): Multimodal LLM based OCR. Runs via Ollama. Ideal for very low-quality scans.

### LLM Providers (`LLM_PROVIDER`)
- **`ollama`** (Default): For local, privacy-first extraction. Requires an Ollama instance.
- **`openai`**: For high-performance cloud extraction. Requires `OPENAI_API_KEY`.

### Model Choice (`LLM_MODEL`)
- **Default**: `qwen3.5:9b`.
- **Note**: Ensure the model is pulled locally (`ollama pull qwen3.5:9b`) before starting the pipeline.

## Ingestion Sources

Each ingestion source has its own configuration block.

| Variable | Description | Default |
|---|---|---|
| `INBOX_PATH` | Local folder to watch for files | `./inbox` |
| `MAX_RECEIPT_AGE_DAYS` | Skip receipts older than this | `365` |
| `DATABASE_PATH` | Path to SQLite database | `processed_receipts.db` |

### Telegram Integration
- **`TELEGRAM_BOT_TOKEN`**: The token from @BotFather.
- **`TELEGRAM_ALLOWED_USERS`**: A comma-separated list of numeric Telegram User IDs. **Crucial for security.**
- **Commands**: `/start`, `/help`, `/status`.

### Google Drive Integration
- **`GDRIVE_CREDENTIALS_FILE`**: Path to `service_account.json` (recommended) or OAuth `credentials.json`.
- **`GDRIVE_FOLDER_ID`**: The ID of the folder to poll.
- **Scopes**: The app requires `https://www.googleapis.com/auth/drive.file` or `https://www.googleapis.com/auth/drive.readonly`.
- **OAuth2 Token Refresh**: If using a User Account, the pipeline automatically refreshes the token using the `token.json` file. Ensure `GDRIVE_CREDENTIALS_FILE` remains accessible to allow for refresh token exchange.

## Security & Dashboard

- **`SECRET_KEY`**: A secure random string used for session security. Change this in production.
- **`REVIEW_USERNAME`**: Username for accessing the Review Dashboard. Defaults to `admin`.
- **`REVIEW_PASSWORD`**: Password for accessing the Review Dashboard. Defaults to `admin`.
- **`REVIEW_DIR`**: Where files waiting for manual approval are stored. Defaults to `./review_queue`.
