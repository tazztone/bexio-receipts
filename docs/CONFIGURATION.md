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
- **`DEFAULT_BOOKING_ACCOUNT_ID`**: (Required) Default bexio account ID for new expenses (e.g., `630`).
- **`DEFAULT_BANK_ACCOUNT_ID`**: (Required) Default bexio bank account ID for payments (e.g., `1`).
- **`DEFAULT_VAT_RATE`**: Default Swiss VAT rate (8.1, 2.6, or 3.8). Defaults to `8.1`.
- **`DEFAULT_PAYMENT_TERMS_DAYS`**: Number of days for payment terms. Defaults to `30`.

## OCR & Extraction Strategy

The system supports two OCR engines and multiple LLM providers.

### OCR Engines (`OCR_ENGINE`)
- **`paddleocr`**: Runs locally. Fast. Requires `paddlepaddle` and `paddleocr` Python packages.
- **`glm-ocr`** (Default): Multimodal LLM based OCR. Runs via Ollama. Ideal for very low-quality scans.

| Variable | Description | Default |
|---|---|---|
| `OCR_ENGINE` | `glm-ocr` or `paddleocr` | `glm-ocr` |
| `GLM_OCR_URL` | URL for the Ollama instance running GLM-OCR | `http://localhost:11434` |
| `GLM_OCR_MODEL` | Model name for GLM-OCR in Ollama | `glm-ocr` |
| `OCR_CONFIDENCE_THRESHOLD` | Confidence below which receipts are flagged | `0.85` |

### LLM Providers (`LLM_PROVIDER`)
- **`ollama`** (Default): For local, privacy-first extraction. Requires an Ollama instance.
- **`openai`**: For high-performance cloud extraction. Requires `OPENAI_API_KEY`.

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `ollama` or `openai` | `ollama` |
| `LLM_MODEL` | The specific LLM model to use | `qwen3.5:9b` |
| `OLLAMA_URL` | URL for the Ollama instance | `http://localhost:11434` |
| `OPENAI_API_KEY` | Your OpenAI API key (if using `openai`) | `None` |

## Ingestion Sources

Each ingestion source has its own configuration block.

| Variable | Description | Default |
|---|---|---|
| `INBOX_PATH` | Local folder to watch for files | `./inbox` |
| `MAX_RECEIPT_AGE_DAYS` | Skip receipts older than this | `365` |
| `DATABASE_PATH` | Path to SQLite database | `processed_receipts.db` |

### Email Integration (IMAP)
- **`IMAP_SERVER`**: IMAP server hostname (e.g., `imap.gmail.com`).
- **`IMAP_USER`**: Email address.
- **`IMAP_PASSWORD`**: Password or App Password.
- **`IMAP_FOLDER`**: Folder to monitor. Defaults to `INBOX`.
- **`IMAP_POLL_INTERVAL`**: Seconds between polls. Defaults to `300`.

### Telegram Integration
- **`TELEGRAM_BOT_TOKEN`**: The token from @BotFather.
- **`TELEGRAM_ALLOWED_USERS`**: A comma-separated list of numeric Telegram User IDs. **Crucial for security.**
- **Commands**: `/start`, `/help`, `/status`.

### Google Drive Integration
- **`GDRIVE_CREDENTIALS_FILE`**: Path to `service_account.json` (recommended) or OAuth `credentials.json`.
- **`GDRIVE_TOKEN_PATH`**: Path where OAuth2 tokens are stored. Defaults to `token.json`.
- **`GDRIVE_FOLDER_ID`**: The ID of the folder to poll.
- **`GDRIVE_PROCESSED_FOLDER_ID`**: Optional ID where files are moved after processing.
- **`GDRIVE_POLL_INTERVAL`**: Seconds between polls. Defaults to `60`.

## Security & Dashboard

> ⚠️ **Warning**: The default `REVIEW_USERNAME` and `REVIEW_PASSWORD` are both set to `admin`. **Change these immediately** if your dashboard is accessible over a network.

- **`SECRET_KEY`**: A secure random string used for session security. Change this in production.
- **`REVIEW_USERNAME`**: Username for accessing the Review Dashboard. Defaults to `admin`.
- **`REVIEW_PASSWORD`**: Password for accessing the Review Dashboard. Defaults to `admin`.
- **`REVIEW_USERS`**: Multi-user support JSON string `{"username": "password"}`.
- **`REVIEW_DIR`**: Where files waiting for manual approval are stored. Defaults to `./review_queue`.
