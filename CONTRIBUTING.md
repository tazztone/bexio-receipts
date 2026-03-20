# Contributing to bexio-receipts

First off, thank you for considering contributing to bexio-receipts! It's people like you that make this tool better.

## How to Contribute

1.  **Report Bugs**: Use the bug report template in the `.github/ISSUE_TEMPLATE/` directory.
2.  **Suggest Features**: Use the feature request template in the `.github/ISSUE_TEMPLATE/` directory.
3.  **Code Contributions**:
    *   Fork the repository.
    *   Create a new branch (`git checkout -b feature/your-feature`).
    *   Ensure all tests pass and coverage is at least **85%**.
    *   Ensure code is formatted and linted properly.
    *   Commit your changes with a descriptive message.
    *   Push to your branch and create a Pull Request.

## Local Development Setup

### 1. Prerequisites
- [uv](https://github.com/astral-sh/uv) installed.
- System dependencies for OCR (on Linux: `libpoppler-cpp-dev`).

### 2. Setup environment
```bash
# Sync dependencies
uv sync --all-extras --dev

# Install pre-commit hooks
uv run pre-commit install
```

### 3. Running the Dashboard locally
```bash
cp .env.example .env
# Edit .env with your local settings
uv run bexio-receipts serve
```

## Pull Request Process

- **Branching**: Use `feature/` for new features and `fix/` for bug fixes.
- **Tests**: PRs will not be merged unless they include tests for new functionality and satisfy the CI check.
- **Reviews**: One maintainer must approve the PR before merging.
- **Rebase**: Please rebase your branch on `main` before submitting to keep a clean history.

## Code Style & Standards

- **Formatting**: We use `ruff` for formatting and linting. The configuration is in `pyproject.toml`.
- **Typing**: The project uses strict type hints where possible. Use `mypy` to verify.
- **Complexity**: Keep functions small and modular.

## Documentation

- **Normative Docs**: Always update `docs/` and `README.md` for logic changes.
- **Archive**: The `docs/archive/` directory is for **historical reference only**. Do not add new planning files there.
- **ADRs**: Instead, create a new **Architecture Decision Record (ADR)** in `docs/DECISIONS.md`. See [docs/DECISIONS.md](docs/DECISIONS.md) for the preferred format.

## Repository Structure

- **`uv.lock`**: We commit the lockfile to ensure reproducible builds across environments. Do not manually edit this file; use `uv lock` or `uv sync` to update it.

## Testing

This project uses `pytest` and maintains a strict **minimum 85%** test coverage. 
```bash
# Run all tests
uv run pytest tests/ --cov=src

# Run a single test
uv run pytest tests/test_validation.py

# Dry-run validation
uv run bexio-receipts process my_receipt.png --dry-run
```
Please include tests with any new functionality.
