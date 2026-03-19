# bexio-receipts 🧾🚀

An automated pipeline to ingest, OCR, and extract data from receipts directly into bexio.

## Features

- **Multi-Source Ingestion:**
  - **Folder Watcher:** Monitors a local directory for new files.
  - **Email (IMAP):** Automatically downloads attachments from an inbox.
  - **Telegram Bot:** Send photos or PDFs directly to the bot for processing.
  - **Google Drive:** Polls a specific Drive folder for new receipts.
- **Multi-Engine OCR:**
  - **PaddleOCR (Default):** High-performance PP-OCRv5 with orientation and unwarping support.
  - **GLM-OCR:** A lightweight (0.9B) multimodal LLM for high-accuracy text and table recognition (via Ollama).
- **Intelligent Extraction:** Uses **Pydantic AI** with OpenAI or Ollama (e.g., Qwen2.5) to parse OCR text into structured data.
- **Swiss Business Rules:** Built-in validation for Swiss VAT rates (8.1%, 2.6%, 3.8%) and 5-rappen rounding tolerance.
- **bexio Integration:** Automatic file upload and expense creation via the bexio API (v3/v4).
- **Review Dashboard:** A web-based interface (FastAPI + HTMX) to manually correct and approve receipts that fail validation.

## Architecture

```
Folder Watcher  ┐
Email (IMAP)    │
Telegram Bot    ┼─▶ OCR (PaddleOCR/GLM-OCR) ─▶ LLM Extraction ─▶ Validation ─▶ bexio API
Google Drive    ┘                                                    │ fail
                                                                     ▼
                                                               Review Dashboard (FastAPI/HTMX)
```

## Setup

### Prerequisites

- [uv](https://github.com/astral-sh/uv) installed.
- [Ollama](https://ollama.com/) (if using GLM-OCR or local LLM extraction).
- A [bexio Personal Access Token](https://docs.bexio.com/#section/Authentication).

### Installation

> **Note on Dependencies:** The default installation includes `paddlepaddle` and `paddleocr`, which are large dependencies (~500MB+ installed). For a lightweight alternative or cleaner isolation, a Docker-only deployment path is highly recommended.

```bash
# Clone the repository
git clone https://github.com/tazztone/bexio-receipts.git
cd bexio-receipts

# Install dependencies
uv sync

# (Optional) Pull Ollama models
ollama pull glm-ocr        # for OCR
ollama pull qwen3.5:9b     # for extraction (https://huggingface.co/Qwen/Qwen3.5-9B)
```

### Configuration

Create a `.env` file in the root directory:

```ini
BEXIO_API_TOKEN=your_bexio_token
BEXIO_BASE_URL=https://api.bexio.com

# OCR Settings
OCR_ENGINE=paddleocr  # Options: paddleocr, glm-ocr
OCR_CONFIDENCE_THRESHOLD=0.85

# If using GLM-OCR (via Ollama)
GLM_OCR_MODEL=glm-ocr
GLM_OCR_URL=http://localhost:11434

# LLM Settings (for extraction)
LLM_PROVIDER=ollama  # Options: ollama, openai
LLM_MODEL=qwen3.5:9b

# Default bexio accounts (Required for expense creation)
DEFAULT_BOOKING_ACCOUNT_ID=123
DEFAULT_BANK_ACCOUNT_ID=456

# Ingestion Settings
DATABASE_PATH=processed_receipts.db
REVIEW_DIR=./review_queue
MAX_RECEIPT_AGE_DAYS=365

# Telegram Bot (Optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_USERS=1234567,8901234  # Comma-separated list of user IDs (Required for access)

# Google Drive (Optional)
GDRIVE_CREDENTIALS_FILE=service_account.json
GDRIVE_FOLDER_ID=your_folder_id
GDRIVE_POLL_INTERVAL=60
GDRIVE_PROCESSED_FOLDER_ID=optional_archive_folder_id
```

## Usage

### CLI

**Process a single receipt file:**
```bash
uv run bexio-receipts process path/to/receipt.png
```

**Run a dry-run (OCR and extraction only):**
```bash
# This mode skips the bexio API push entirely — useful for testing locally without credentials.
uv run bexio-receipts process path/to/receipt.png --dry-run
```

### Review Dashboard

If a receipt fails validation or has low OCR confidence, it is moved to the `REVIEW_DIR`. Start the web-based review interface to manage these:

```bash
uv run bexio-receipts serve
```
Then visit `http://127.0.0.1:8000` in your browser.

### Automation

**Watch a local folder for new receipts:**
```bash
uv run bexio-receipts watch-folder --path ./inbox
```

**Watch an email inbox (IMAP) for new receipts:**
```bash
uv run bexio-receipts watch-email
```

**Ingest via Telegram Bot:**
```bash
uv run bexio-receipts watch-telegram
```

**Watch a Google Drive folder for new receipts:**
```bash
uv run bexio-receipts watch-gdrive
```

**Authenticate Google Drive (Interactive):**
```bash
uv run bexio-receipts gdrive-auth
```

## Ingestion Sources

### Google Drive Setup

The Google Drive ingestor supports two authentication modes:

- **Service Account (Recommended for Servers):**
  1. Create a Service Account in the [Google Cloud Console](https://console.cloud.google.com/).
  2. Download the JSON key file and set `GDRIVE_CREDENTIALS_FILE` to its path.
     *Note: Ensure this file has restrictive permissions (e.g., `chmod 600 credentials.json`) to protect your service account token.*
  3. Share your target Google Drive folder with the Service Account's email address (e.g., `your-sa@project.iam.gserviceaccount.com`).
- **User Account (OAuth2):**
  1. Create an OAuth 2.0 Client ID in the Google Cloud Console.
  2. Download the `credentials.json` and set `GDRIVE_CREDENTIALS_FILE` to its path.
     *Note: Ensure this file has restrictive permissions (e.g., `chmod 600 credentials.json`) to protect your OAuth client secrets.*
  3. Run the interactive authentication command:
     ```bash
     uv run bexio-receipts gdrive-auth
     ```
  4. This saves a `token.json` file, allowing the watcher to run headlessly thereafter.

**Optional Archiving:** If `GDRIVE_PROCESSED_FOLDER_ID` is set, processed files will be moved to that folder in Google Drive instead of being left in the inbox.

---

## bexio Integration (v4)

The pipeline intelligently chooses between two bexio endpoints:
- **Purchase Bills (Recommended):** If a merchant is identified, it creates a full Bill with line items per VAT rate. This supports multi-VAT receipts and supplier tracking.
- **Expenses:** If no merchant is identified, it falls back to a simple expense booking.
- **Reliability:** Every API call includes automatic retry behavior (3 attempts with exponential backoff) for transient 429 and 5xx errors.

## Smart Features

- **Smart Categorization:** Remembers the last used booking account for each merchant (SQLite-backed, survives restarts).
- **Persistent Deduplication:**
  - **Google Drive ID Tracking:** Drive file IDs are tracked in the database to prevent re-downloads.
  - **Content Hashing:** A SHA-256 hash is used to prevent double-booking even if a file is re-uploaded.
- **Handling "Review" Status:**
  - Files that fail validation are moved to the review queue.
  - The watcher marks these as "seen" to avoid infinite re-processing.
  - To re-ingest a file after deleting it from the review queue, you must manually clear its ID from the `gdrive_seen_files` table in the database.
- **Statistics Dashboard:** Track your processing volume and reclaimed VAT via the `/stats` view.

## Development & Testing

### Running Tests

The project includes a comprehensive test suite using `pytest` and `pytest-asyncio`.

```bash
uv run pytest tests/ -v
```

### Project Structure

- `src/bexio_receipts/ocr.py`: Unified OCR layer for PaddleOCR and GLM-OCR.
- `src/bexio_receipts/extraction.py`: Pydantic AI agent for structured data extraction.
- `src/bexio_receipts/validation.py`: Swiss-specific business rules and data validation.
- `src/bexio_receipts/server.py`: FastAPI server for the review dashboard.
- `src/bexio_receipts/bexio_client.py`: Async bexio API client with retries.
- `src/bexio_receipts/pipeline.py`: Orchestrator for the full ingestion flow.
- `src/bexio_receipts/cli.py`: Command-line interface with `process` and `serve` commands.
- `docs/`: Internal implementation plans and design documents.
