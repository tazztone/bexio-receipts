# Development Guide

This document covers internal best practices, testing strategies, and the design patterns used in `bexio-receipts`.

## 🛠️ Environment Setup

The project uses `uv` for dependency management.

```bash
uv sync                # Setup virtualenv and install dependencies
uv run bexio-receipts  # Run the CLI
```

### Prerequisites
- Python 3.12+ (tested up to 3.13)
- [PaddlePaddle-GPU](https://www.paddlepaddle.org.cn/install/quick?docurl=/install/quick_en.html) (optional, for faster OCR)
- [libpoppler-cpp-dev](https://poppler.freedesktop.org/) (required for `pdf2image`)

## 🧪 Testing Strategy

We prioritize **Automated Verification** over manual tests.

```bash
uv run pytest tests/            # Run the test suite
uv run pytest --cov=src tests/  # Run with coverage report
```

### Key Test Patterns
1. **Mocking HTTP**: We use `respx` to mock bexio and LLM API calls.
2. **Schema Validation**: Tests in `test_models.py` ensure that normalization logic (like merchant name cleaning) works consistently.
3. **Database Isolation**: Always use the `tmp_path` fixture for SQLite tests to avoid side-effects between runs.

---

## 🏗️ Internal Best Practices

### 1. Robust API Calls
Always use the `@BEXIO_RETRY` decorator for any remote API calls. It handles transient network errors and rate limits (`429`) with exponential backoff.

### 2. Configuration & Fail-Fast
New settings must be added to `Settings` in `config.py`. We prefer mandatory fields over "safe" fallbacks—it's better to fail at startup than to run with insecure or unexpected state.

### 3. Database Resource Management
The `DuplicateDetector` class should always be used as a context manager:
```python
with DuplicateDetector(path) as db:
    db.mark_processed(...)
```

### 4. Static Analysis
Pre-commit hooks for `ruff` and `mypy` are mandatory. All code must pass type-checking before being committed. We use `type: ignore` sparingly and only for 3rd-party library inconsistencies.

---

## 📈 Audit Findings & Evolution
Significant architectural changes are documented in the [Changelog](../CHANGELOG.md).
Strategic takeaways from the 2024 Deep Audit are archived in `docs/archive/audit_findings_2024.md`.
