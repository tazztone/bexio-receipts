# Local Development Setup Guide

This document summarizes the custom local configuration for this environment.

## 🧠 LLM Configuration (Ollama)
The project is configured to use the official Qwen 3.5 9B model via your host's Ollama instance.

- **Model Name**: `qwen3.5` (Official Library)
- **Ollama Host**: `http://host.docker.internal:11434` (Ollama running on host, listening on `0.0.0.0`)
- **GPU Acceleration**: Recommended for optimal performance.

## 🔍 OCR Configuration
- **Engine**: `glm-ocr` (Default)
  - **Model**: `glm-ocr`
  - **Architecture**: GLM-4-V (1.1B) via Ollama.
  - **Host**: Uses the same host-based Ollama instance as the LLM to leverage GPU acceleration.
  - **Advantage**: Superior accuracy on Swiss receipts with minimal container-side overhead.

## 🚀 Docker Environment
The environment uses a `Makefile` for unified management:
- `make up`: Starts the dashboard, mock bexio, watcher, and mock imap.
- `make process-test`: Runs a full pipeline test (OCR -> Extraction -> Dry Run) using a sample receipt.
- `make logs`: Follows logs for all services.
- `make down`: Stops the environment.

## 🛠️ Mock Environment & Dashboard
- **Bexio API**: Redirected to `http://mock-bexio:8001` (FastAPI Mock Server). No real tokens are used in the local environment.
- **Setup Wizard**: Access `http://localhost:8000/setup` to verify all components (DB, OCR, LLM, Bexio) are healthy.
- **Review Queue**: Receipts failing validation (e.g., missing date) are sent to `http://localhost:8000/` for manual review.

## 🔧 Troubleshooting
- **Ollama Connection**: Ensure Ollama is running on your host and listening on all interfaces (`OLLAMA_HOST=0.0.0.0`).
- **Model Pulls**: Use the **Setup Wizard** or `ollama pull qwen3.5 && ollama pull glm-ocr` on your host.
- **Rebuilding**: Run `make up` after changing Python dependencies; the context is optimized to exclude `.venv` and `.gguf` files.
