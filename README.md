# bexio-receipts 🧾🚀

[![CI](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml/badge.svg)](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-85%25-green)](.coveragerc)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

An automated pipeline to ingest, OCR, and extract data from receipts directly into bexio.

---

## ⚡ Quick Start

### Docker (Recommended)
```bash
# Clone and start everything
git clone https://github.com/tazztone/bexio-receipts.git && cd bexio-receipts
cp .env.example .env  # Edit this with your bexio token
docker compose up -d
```

### Local (uv)
```bash
uv sync
uv run bexio-receipts process path/to/receipt.png --dry-run
```

---

## 📖 Table of Contents
- [Features](#-features)
- [Architecture](#-architecture)
- [Setup](#-setup)
- [Usage](#-usage)
- [Ingestion Sources](#-ingestion-sources)
- [Troubleshooting](#-troubleshooting)
- [Development](#-development)
- [License](#-license)

---

## ✨ Features

- **Multi-Source Ingestion:**
  - **Folder Watcher:** Monitors a local directory for new files.
  - **Email (IMAP):** Automatically downloads attachments from an inbox.
  - **Telegram Bot:** Send photos or PDFs directly to the bot for processing.
  - **Google Drive:** Polls a specific Drive folder for new receipts.
- **Multi-Engine OCR:**
  - **PaddleOCR (Default):** High-performance PP-OCRv5 with orientation and unwarping support.
  - **GLM-OCR:** A lightweight (0.9B) multimodal LLM for high-accuracy text and table recognition (via Ollama).
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

> **Note on Dependencies:** The default installation includes `paddlepaddle` and `paddleocr`, which are large dependencies (~500MB+ installed). For a lightweight alternative or cleaner isolation, a Docker-only deployment path is highly recommended.

```bash
git clone https://github.com/tazztone/bexio-receipts.git && cd bexio-receipts
uv sync

# Pull Ollama models
ollama pull glm-ocr        # for OCR
ollama pull qwen3.5:9b     # for extraction
```

### Docker

The project includes an optimized multi-stage `Dockerfile` with build caching.

```bash
docker compose up -d
```
The dashboard will be available at `http://localhost:8000`.

### Configuration

Copy `.env.example` to `.env` and fill in your credentials. Key variables include:
- `BEXIO_API_TOKEN`: Your API token.
- `OCR_ENGINE`: `paddleocr` or `glm-ocr`.
- `LLM_MODEL`: e.g., `qwen3.5:9b`.

---

## 🚀 Usage

### CLI

**Process a single receipt:**
```bash
uv run bexio-receipts process path/to/receipt.png
```

**Run a dry-run (OCR and extraction only):**
```bash
uv run bexio-receipts process path/to/receipt.png --dry-run
```

### Review Dashboard

Start the web interface to manage files that fail validation:
```bash
uv run bexio-receipts serve
```

---

## 📥 Ingestion Sources

### Google Drive Setup
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
│   ├── ocr.py           # Unified OCR layer
│   ├── extraction.py    # LLM structured extraction
│   ├── validation.py    # Swiss VAT & business rules
│   ├── server.py        # Dashboard backend
│   └── bexio_client.py   # API interactions
├── docs/                # Extended documentation
├── tests/               # Pytest suite
└── Dockerfile           # Optimized multi-stage build
```

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): System flow and engine details.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): Dev environment setup.
- [CHANGELOG.md](CHANGELOG.md): History of changes.

---

## 🔗 Useful Links
- [bexio API Documentation](https://docs.bexio.com/)
- [GLM-OCR](https://github.com/zai-org/GLM-OCR)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.
