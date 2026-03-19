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
- **uv**: `curl -LsSf https://astral-sh/uv/install.sh | sh`
- **System Dependencies (Poppler)**:
  - **Linux (Debian/Ubuntu)**: `sudo apt-get install libpoppler-cpp-dev`
  - **macOS**: `brew install poppler`
  - **Windows**: [Download binaries](https://github.com/oschwartz10612/poppler-windows/releases) and add to PATH.

### Installation
```bash
uv sync --all-extras --dev
uv run pre-commit install
```

## Testing Strategy

### Unit & Integration Tests
We use `pytest`. The suite includes mocks for bexio and LLM providers.
```bash
uv run pytest tests/
```

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
