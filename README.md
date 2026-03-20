# bexio-receipts 🧾🚀

[![CI](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml/badge.svg)](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-86%25-green)](https://github.com/tazztone/bexio-receipts/actions)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

An automated pipeline to ingest, OCR, and extract data from receipts directly into bexio.

---

## 🚀 Quick Start

Get up and running in minutes with the interactive setup wizard:

```bash
uv run bexio-receipts init --quickstart
```

The `--quickstart` flag will:
1.  **Validate** your Bexio token and display your company name.
2.  **Configure** default local models (Qwen 3.5 & GLM-OCR).
3.  **Process** a bundled demo receipt to verify your local LLM/OCR stack immediately.

### What you'll see first
1.  **Interactive Setup:** Run `init` to connect your Bexio account.
2.  **System Health:** Start the dashboard (`serve`) and visit `/setup` to ensure your hardware is ready.
3.  **First Ingestion:** Drop a receipt in `inbox/` or send it to your Telegram bot.
4.  **Review Queue:** Visit the dashboard to triage any receipts with low confidence or validation errors.

---

## 📖 Table of Contents
- [Features](#-features)
- [Architecture](#-architecture)
- [Setup](#-setup)
- [Usage](#-usage)
- [Ingestion Sources](#-ingestion-sources)
- [Operations Guide](docs/OPERATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Development](docs/DEVELOPMENT.md)
- [License](#-license)

---

## ✨ Features

- **Multi-Source Ingestion:**
  - **Folder Watcher:** Monitors a local directory for new files.
  - **Email (IMAP):** Automatically downloads attachments from an inbox.
  - **Telegram Bot:** Send photos or PDFs directly to the bot for processing.
  - **Google Drive:** Polls a specific Drive folder for new receipts.
- **Multi-Engine OCR:**
  - **GLM-OCR (Default):** A lightweight (0.9B) multimodal LLM for high-accuracy text and table recognition (via Ollama).
  - **PaddleOCR:** High-performance PP-OCRv5 with orientation and unwarping support.
- **Intelligent Extraction:** Uses **Pydantic AI** with local LLMs (e.g., Qwen2.5) to parse OCR text into structured data.
- **Swiss Business Rules:** Built-in validation for Swiss VAT rates (8.1%, 2.6%, 3.8%) and 5-rappen rounding tolerance.
- **bexio Integration:** Automatic file upload and expense creation via the bexio API (v3/v4).
- **Review Dashboard:** A web-based interface (FastAPI + HTMX) to manually correct and approve receipts that fail validation.

---

## 🏗️ Architecture

```mermaid
graph TD
    subgraph Ingestion
        FW["Watcher"] --> P["Pipeline"]
        EM["Email"] --> P
        TB["Telegram"] --> P
        GD["GDrive"] --> P
    end

    subgraph Processing
        P --> OCR["OCR (Paddle/GLM)"]
        OCR --> LLM["LLM Extraction"]
        LLM --> VAL["Validation"]
    end

    subgraph Integration
        VAL -- Pass --> BEX["bexio API"]
        VAL -- Fail --> RD["Review Dashboard"]
        RD -- Approved --> BEX
    end

    BEX -- 429/5xx --> Retry["Retry Logic"]
    Retry --> BEX
    P -- SHA256 --> DB["Deduplication"]
```
*See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deep dive.*

---

## ⚙️ Setup

### Prerequisites

- [uv](https://github.com/astral-sh/uv) installed.
- [Ollama](https://ollama.com/) (if using GLM-OCR or local LLM extraction).
- A [bexio Personal Access Token](https://docs.bexio.com/#section/Authentication).

### Installation

```bash
git clone https://github.com/tazztone/bexio-receipts.git && cd bexio-receipts
uv sync

# Copy example environment
cp .env.example .env

# Interactive Setup (Recommended)
uv run bexio-receipts init

# Or manually pull Ollama models
ollama pull glm-ocr        # for OCR
ollama pull qwen3.5:9b     # for extraction
```

### Docker

The project includes an optimized multi-stage `Dockerfile`.

```bash
docker compose up -d
```
The dashboard will be available at `http://localhost:8000`.

---

## 🚀 Usage

### CLI

The CLI is powered by [Typer](https://typer.tiangolo.com/) and provides grouped commands.

**Interactive Setup:**
```bash
uv run bexio-receipts init
```

**Process a single receipt:**
```bash
uv run bexio-receipts process path/to/receipt.png
```

**Run a dry-run (OCR and extraction only):**
```bash
uv run bexio-receipts process path/to/receipt.png --dry-run
```
*Note: Dry-run performs OCR and LLM extraction but does NOT write to the database or upload to bexio.*

**Watchers:**
```bash
uv run bexio-receipts watch folder --path ./my-inbox
uv run bexio-receipts watch telegram
uv run bexio-receipts watch email
uv run bexio-receipts watch gdrive
```

**Mappings:**
```bash
uv run bexio-receipts mapping export mappings.json
uv run bexio-receipts mapping import mappings.json
```

### Review Dashboard

Start the web interface to manage files that fail validation:
```bash
uv run bexio-receipts serve
```

The new dashboard includes:
- **Receipt Thumbnails**: Quick visual identification in the queue.
- **Date Column**: Sort and track receipts by transaction date.
- **Bulk Actions**: Discard multiple invalid receipts at once.
- **OCR Confidence**: See how confident the system was in its extraction.
- **Zoomable Previews**: Click any receipt to see the full-size image.

---

## 📥 Ingestion Sources

### Folder Watcher
Simply drop files into the configured `INBOX_PATH` (default: `./inbox`).

### Email (IMAP)
Configure `IMAP_SERVER`, `IMAP_USER`, and `IMAP_PASSWORD`. The bot will poll for new unread emails with attachments.

### Telegram
1. Create a bot via [@BotFather](https://t.me/botfather).
2. Set `TELEGRAM_BOT_TOKEN` and your numeric ID in `TELEGRAM_ALLOWED_USERS`.
3. Run `uv run bexio-receipts watch telegram`.

### Google Drive
- **Service Account (Recommended):** Share your Drive folder with the SA email.
- **User Account (OAuth2):** Run `uv run bexio-receipts gdrive-auth` to generate `token.json`.

---

## 🛠️ Troubleshooting

- **Ollama Connection Error:** Ensure Ollama is running (`ollama serve`) and `OLLAMA_HOST` is correctly set.
- **PaddleOCR Installation Failures:** On Linux, ensure `libpoppler-cpp-dev` is installed. On macOS, use `brew install poppler`.
- **bexio 401 Unauthorized:** Verify your `BEXIO_API_TOKEN` hasn't expired and has the correct permissions.
- **Docker Port Conflicts:** If port 8000 is taken, change the mapping in `docker-compose.yml`.

---

## 🏗️ Project Structure

```text
.
├── src/bexio_receipts/
│   ├── ocr.py           # Unified OCR layer (Paddle/GLM)
│   ├── extraction.py    # LLM structured extraction (Pydantic AI)
│   ├── validation.py    # Swiss VAT & business rules
│   ├── server.py        # Dashboard backend (FastAPI + HTMX)
│   ├── bexio_client.py  # bexio API interactions (httpx)
│   ├── pipeline.py      # Core ingestion logic
│   ├── database.py      # SQLite & deduplication
│   ├── watcher.py       # Folder filesystem monitoring
│   ├── telegram_bot.py  # Telegram bot interface
│   ├── gdrive_ingest.py # Google Drive polling
│   ├── email_ingest.py  # IMAP email attachment polling
│   ├── config.py        # Pydantic Settings
│   └── models.py        # Pydantic data models
├── docs/                # Extended documentation
├── tests/               # Pytest suite
└── Dockerfile           # Optimized multi-stage build
```

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: System flow and engine details.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md): Detailed env var reference.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): Development setup and best practices.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): Production setup and maintenance tasks.
- [CHANGELOG.md](CHANGELOG.md): History of changes.

---

## 🚧 Known Limitations

- **Hardware**: local extraction with `qwen3.5:9b` via Ollama requires at least 16GB RAM and is significantly faster with a CUDA-compatible GPU.
- **Language**: PaddleOCR (default) is optimized for Latin-based languages. Handwritten or non-Latin receipts may require `glm-ocr`.
- **Merchant Match**: Automatic contact creation in bexio relies on high-confidence merchant name extraction.

---

## 🔗 Useful Links
- [bexio API Documentation](https://docs.bexio.com/)
- [GLM-OCR](https://github.com/zai-org/GLM-OCR)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.
