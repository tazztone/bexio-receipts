# Local Development Setup Guide

This guide describes how to set up a local development environment for `bexio-receipts`.

## 🧠 LLM Configuration (Ollama)
The project is optimized for use with [Ollama](https://ollama.com/) for local extraction.

- **Recommended Model**: `qwen3.5:9b` (or `qwen2.5:7b` for lower RAM).
- **Ollama Host**: Default is `http://localhost:11434`. 
- **Docker Note**: If running the app in Docker and Ollama on the host, use `http://host.docker.internal:11434` and ensure Ollama is listening on `0.0.0.0`.

## 🔍 OCR Configuration
- **Engine**: `glm-ocr` (Default)
  - **Model**: `glm-ocr`
  - **Architecture**: GLM-4-V (1.1B) via Ollama.
  - **Advantage**: Superior accuracy on Swiss receipts with minimal overhead.
- **Alternative**: `paddleocr` (Fast, runs entirely in Python).

## 🚀 Setup & Initialization
The project uses `uv` for dependency management.

1. **Sync dependencies**: `uv sync`
2. **Initialize Configuration**: Run `uv run bexio-receipts init` to generate your `.env` file interactively.
3. **Pull Models**:
   ```bash
   ollama pull glm-ocr
   ollama pull qwen3.5:9b
   ```
   Or use the **Setup Wizard** at `http://localhost:8000/setup` to verify health and pull models.

## 🚀 Docker Environment
A `docker-compose.yml` and `Makefile` are provided for containerized development.

```bash
make build  # Build the image
make up     # Start all services
```

## 🛠️ Mock Environment
For development without a real bexio account, you can use a mock server.

- **Mock Server**: The included `tests/mock_bexio.py` can be run to simulate the bexio API.
- **Configuration**: Set `BEXIO_BASE_URL=http://localhost:8001` in your `.env`.
- **Dashboard**: Access the review interface at `http://localhost:8000`.

## 🔧 Troubleshooting
- **Ollama Connection**: Ensure Ollama is running (`ollama serve`) and accessible.
- **System Dependencies**: Ensure `poppler` is installed for PDF support.
- **Port Conflicts**: If port 8000 or 11434 is occupied, adjust your `.env` and `docker-compose.yml`.
