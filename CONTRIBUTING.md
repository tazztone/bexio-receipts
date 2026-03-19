# Contributing to bexio-receipts

First off, thank you for considering contributing to bexio-receipts! It's people like you that make this tool better.

## How to Contribute

1.  **Report Bugs**: Use the bug report template in the Issues tab.
2.  **Suggest Features**: Use the feature request template in the Issues tab.
3.  **Code Contributions**:
    *   Fork the repository.
    *   Create a new branch (`git checkout -b feature/your-feature`).
    *   Ensure all tests pass (`uv run pytest tests/`).
    *   Ensure code is formatted with `ruff` (`uv run ruff check .` and `uv run ruff format .`).
    *   Commit your changes with a descriptive message.
    *   Push to the branch and create a Pull Request.

## Development Setup

See the [README.md](README.md) for detailed setup instructions using `uv`.

Ensure you configure your `.env` properly for local testing if running against a live API.

## Testing

This project uses `pytest` and maintains a strict >85% test coverage. Please include tests with any new functionality.
