# bexio-receipts 🧾🚀

An automated pipeline to ingest, OCR, and extract data from receipts directly into bexio.

## Features

- **Multi-Engine OCR:**
  - **PaddleOCR (Default):** High-performance PP-OCRv5 with orientation and unwarping support.
  - **GLM-OCR:** A lightweight (0.9B) multimodal LLM for high-accuracy text and table recognition (via Ollama).
- **Intelligent Extraction:** Uses **Pydantic AI** with OpenAI or Ollama (e.g., Qwen2.5) to parse OCR text into structured data.
- **Swiss Business Rules:** Built-in validation for Swiss VAT rates (8.1%, 2.6%, 3.8%) and 5-rappen rounding tolerance.
- **bexio Integration:** Automatic file upload and expense creation via the bexio API (v3/v4).
- **Review Queue:** Receipts with low confidence or validation errors are saved to a local JSON review queue for manual inspection.

## Architecture

```
Ingestion ──▶ OCR (PaddleOCR/GLM-OCR) ──▶ LLM Extraction (Pydantic AI) ──▶ Validation ──▶ bexio API
                                                                                │ fail
                                                                                ▼
                                                                          Review Queue
```

## Setup

### Prerequisites

- [uv](https://github.com/astral-sh/uv) installed.
- [Ollama](https://ollama.com/) (if using GLM-OCR or local LLM extraction).
- A [bexio Personal Access Token](https://docs.bexio.com/#section/Authentication).

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd bexio-receipts

# Install dependencies
uv sync
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
LLM_MODEL=qwen2.5:7b

# Default bexio accounts (Required for expense creation)
DEFAULT_BOOKING_ACCOUNT_ID=123
DEFAULT_BANK_ACCOUNT_ID=456
```

## Usage

### CLI

Process a single receipt file:

```bash
uv run bexio-receipts path/to/receipt.png
```

Run a dry-run (OCR and extraction only, no bexio upload):

```bash
uv run bexio-receipts path/to/receipt.png --dry-run
```

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
- `src/bexio_receipts/bexio_client.py`: Async bexio API client.
- `src/bexio_receipts/pipeline.py`: Orchestrator for the full ingestion flow.
- `src/bexio_receipts/cli.py`: Command-line interface.

## Next Steps (Phase 2)

- [ ] FastAPI-based web UI for the review queue (using HTMX).
- [ ] IMAP integration to watch an email inbox for incoming receipts.
- [ ] Folder watcher to automate processing for specific directories.
- [ ] Multi-VAT receipt splitting.
