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

## bexio Integration (v4)

The pipeline intelligently chooses between two bexio endpoints:
- **Purchase Bills (Recommended):** If a merchant is identified, it creates a full Bill with line items per VAT rate. This supports multi-VAT receipts and supplier tracking.
- **Expenses:** If no merchant is identified, it falls back to a simple expense booking.
- **Reliability:** Every API call includes automatic retry behavior (3 attempts with exponential backoff) for transient 429 and 5xx errors.

## Smart Features

- **Smart Categorization:** Remembers the last used booking account for each merchant (SQLite-backed, survives restarts).
- **Duplicate Detection:** Prevents double-booking via SHA-256 file hashing.
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
