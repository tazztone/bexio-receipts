# Development Guide

This document covers internal best practices, testing strategies, and the design patterns used in `bexio-receipts`.

## 🛠️ Environment Setup

The project uses `uv` for dependency management.

```bash
uv sync                # Setup virtualenv and install dependencies
uv run bexio-receipts  # Run the CLI
```

### Prerequisites
- **Python 3.12+**
- **uv**: `curl -LsSf https://docs.astral.sh/uv/install.sh | sh`
- **System Dependencies (Poppler)**:
  - **Linux (Debian/Ubuntu)**: `sudo apt-get install libpoppler-cpp-dev`
  - **macOS**: `brew install poppler`
  - **Windows**: [Download binaries](https://github.com/oschwartz10612/poppler-windows/releases) and add to PATH.

### Installation
```bash
uv sync --all-extras --dev
uv run pre-commit install
```

## 🚀 Local Docker Environment

For containerized development, a `docker-compose.yml` and `Makefile` are provided.

### LLM Configuration (Ollama)
The project is optimized for use with [Ollama](https://ollama.com/) for local extraction.

- **Recommended Model**: `qwen3.5:9b` (or `qwen2.5:7b` for lower RAM).
- **Ollama Host**: Default is `http://localhost:11434`. 
- **Docker Note**: If running the app in Docker and Ollama on the host, use `http://host.docker.internal:11434` and ensure Ollama is listening on `0.0.0.0`.

### Setup & Initialization
1. **Build & Start**:
   ```bash
   make build  # Build the image
   make up     # Start all services
   ```
2. **Initialize Configuration**: Run `uv run bexio-receipts init` to generate your `.env` file interactively.
3. **Pull Models**:
   ```bash
   ollama pull glm-ocr
   ollama pull qwen3.5:9b
   ```
   Alternatively, use the **Setup Wizard** at `http://localhost:8000/setup` to verify health and pull models directly from the UI.

### 🛠️ Mock Environment
For development without a real bexio account, you can use a mock server.

- **Mock Server**: The included `tests/mock_bexio.py` can be run to simulate the bexio API.
- **Configuration**: Set `BEXIO_BASE_URL=http://localhost:8001` in your `.env`.
- **Dashboard**: Access the review interface at `http://localhost:8000`.

## Testing Strategy

### Unit & Integration Tests
We use `pytest`. The suite includes mocks for bexio and LLM providers.
```bash
uv run pytest tests/
```

### Best Practices for Testing
1. **Mocking**: Use the `mock_bexio` fixture to avoid real API calls.
2. **Deterministic Inputs**: Use fixtures in `tests/fixtures/` for consistent OCR results in tests.
3. **Database Isolation**: Always use the `tmp_path` fixture for SQLite tests to avoid side-effects between runs.

### Static Analysis
Before pushing, ensure these pass:
- **Linting**: `uv run ruff check .`
- **Formatting**: `uv run ruff format .`
- **Type Checking**: `uv run mypy src/`

## Internal Best Practices

1. **Type Safety**: All new functions should have type hints. Pre-commit hooks for `ruff` and `mypy` are mandatory.
2. **Validated Models**: Use `Receipt` (Pydantic) for all data passing.
3. **Async first**: Keep I/O non-blocking using `httpx.AsyncClient` and `asyncio`.
4. **API Robustness**: Always use the `@BEXIO_RETRY` decorator for remote calls (handles 429/5xx).
5. **Configuration**: New settings must be added to `Settings` in `config.py`. We prefer mandatory fields over fallbacks.
6. **Database Persistence**: The `DuplicateDetector` class should always be used as a context manager (`with` statement) to ensure proper connection cleanup.
7. **Documentation**:
   - Update `CHANGELOG.md` for every significant change.
   - Refactor `ARCHITECTURE.md` if the data flow changes.
   - Note: The `docs/archive/` directory contains historical design notes and is for context only; it is not normative for the current system.

## 🏗️ Design Rationale (Lessons Learned)

These principles were solidified during the 2024 deep audit:

1. **Surface Latent Bugs**: Surface-level functional tests can miss class signature mismatches. **Static Analysis (Mypy)** and high-coverage integration tests are mandatory to catch runtime crashes before they hit production.
2. **Fail Fast Configuration**: Avoid hardcoded fallbacks for security-sensitive settings (like `secret_key`). Use Pydantic `Settings` to ensure the application fails at startup if the environment is misconfigured.
3. **Cold Path Protection**: Secondary modules (Telegram, GDrive) can accumulate bitrot. CI must exercise all modules via `mypy` and `ruff` regardless of how frequently they are used in production.
4. **Deterministic Resource Cleanup**: Always implement context manager support (`with` statements) for I/O resources (DBs, sockets) to ensure they are closed properly, rather than relying on the garbage collector.

## CI/CD
Our GitHub Actions workflow enforces:
- All tests passing.
- Test coverage > 85%.
- Static analysis (Ruff/Mypy) passing.
- Successful Docker build.

---

## 📈 Audit Findings & Evolution
Significant architectural changes are documented in the [Changelog](../CHANGELOG.md).
Strategic takeaways from the 2024 Deep Audit are archived in `docs/archive/audit_findings_2024.md`.
