# bexio-receipts

[![CI](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml/badge.svg)](https://github.com/tazztone/bexio-receipts/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/)
[![Coverage](https://img.shields.io/badge/coverage-86%25-green)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)

An automated pipeline that ingests receipts (local folder or Google Drive), OCRs them using local AI models, extracts structured data, validates Swiss VAT rules, and submits expense entries to [bexio](https://www.bexio.com/) — with a mandatory human review step before anything is booked.

## Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.12 / 3.13 |
| Web Dashboard | FastAPI + HTMX |
| AI Extraction | Pydantic AI + Qwen 3.5/3.6 VLM (via Ollama) |
| OCR | GLM-OCR SDK (vLLM / SGLang backend) |
| PDF Parsing | pdfplumber |
| bexio API | httpx |
| Database | SQLite (deduplication + learning loop) |
| Ingestion | Local folder watcher + Google Drive polling |
| Packaging | pyproject.toml + uv |
| Containerization | Docker + docker-compose |
| Linting | Ruff |
| Type checking | Mypy |
| Testing | pytest (86% coverage) |

## Architecture

```
src/bexio_receipts/
├── pipeline.py          # Core ingestion orchestrator
├── document_processor.py # Vision/OCR strategy selector
├── ocr.py               # GLM-OCR integration
├── extraction.py        # Pydantic AI structured extraction (3-step LLM pipeline)
├── prompts.py           # VLM/LLM prompt templates
├── validation.py        # Swiss VAT rules (8.1%, 2.6%, 3.8%) + 5-rappen rounding
├── server.py            # FastAPI + HTMX review dashboard
├── bexio_client.py      # bexio REST API client
├── database.py          # SQLite deduplication + per-merchant account learning
├── watcher.py           # Filesystem monitoring (watchdog)
├── gdrive_ingest.py     # Google Drive polling
├── config.py            # Pydantic Settings
└── models.py            # Unified data models (Receipt, VisionExtraction)
```

**Processing flow:** Ingest → SHA-256 dedup → VLM vision extraction (or GLM-OCR fallback) → 3-step LLM pipeline (search → VAT assignment → account classification) → Swiss VAT validation → Review Dashboard → bexio API submission.

A **learning loop** remembers per-merchant, per-VAT-rate account choices so future receipts from the same merchant are auto-classified.

## Key Features

- **Dual ingestion** — local folder watcher + Google Drive polling
- **Smart OCR/Vision** — native PDF text extraction (pdfplumber), VLM vision (Qwen), GLM-OCR fallback for scanned images
- **Swiss business rules** — VAT rate validation (8.1% / 2.6% / 3.8%), 5-rappen rounding, automatic booking account classification
- **Review dashboard** — FastAPI + HTMX web UI with thumbnails, zoomable previews, OCR confidence scores, bulk actions
- **Deduplication** — SHA-256 hash check prevents duplicate entries
- **Docker support** — multi-stage optimized image + docker-compose

## Quick Start

```bash
git clone https://github.com/tazztone/bexio-receipts.git && cd bexio-receipts
uv sync
cp .env.example .env

# Interactive setup wizard (validates bexio token, configures models, runs demo)
uv run bexio-receipts init --quickstart
```

### CLI

```bash
# Process a single receipt
uv run bexio-receipts process path/to/receipt.png

# Dry run (OCR + extraction only, no bexio submission)
uv run bexio-receipts process path/to/receipt.png --dry-run

# Start folder watcher
uv run bexio-receipts watch folder --path ./inbox

# Start review dashboard
uv run bexio-receipts serve
# → http://localhost:8000
```

## Prerequisites

- [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com/) + `qwen3.5:9b` model pulled
- [vLLM](https://github.com/vllm-project/vllm) or SGLang (for GLM-OCR)
- A [bexio Personal Access Token](https://docs.bexio.com/#section/Authentication)

## Documentation

| Doc | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System flow and engine details |
| [Configuration](docs/CONFIGURATION.md) | Full `.env` reference |
| [VLM Performance](docs/VLM_PERFORMANCE.md) | Hardware benchmarks |
| [Development](docs/DEVELOPMENT.md) | Contribution guide |
| [Operations](docs/OPERATIONS.md) | Production setup |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues |

## License

MIT — see [LICENSE](LICENSE).
