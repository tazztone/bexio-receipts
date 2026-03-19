# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Responsible disclosure policy in `SECURITY.md`.
- GitHub Issue Templates for bugs and feature requests.
- Mermaid diagrams in `README.md` and `ARCHITECTURE.md`.
- Troubleshooting guide and Quick Start in `README.md`.

### Fixed
- Corrected Ollama model tag for Qwen in `config.py` and documentation.

## [0.1.2] - 2024-05-25

### Added
- Comprehensive Static Analysis: Added `mypy` and `ruff` checks to CI and pre-commit.
- CI Matrix: Testing against Python 3.12 and 3.13.
- Docker Build Caching: Implemented GitHub Actions layer caching for faster builds.
- CLI Validation: User-friendly field-by-field Pydantic error formatting.

### Changed
- Docker Optimization: Switched to `COPY --from=uv` for leaner and more secure builds; added `CMD` instruction.
- API Modernization: Updated Starlette `TemplateResponse` usage to the newest API.
- Bexio Client: Extracted `BEXIO_RETRY` decorator to unify retry logic across the API client.
- Database: Improved `DuplicateDetector` with context manager support (`with` statement).
- CLI Defaults: `serve` command now defaults to host `0.0.0.0` for easier container access.

### Fixed
- **Security**: Removed hardcoded `SECRET_KEY` fallback in `server.py`; now correctly defaults to settings/env.
- **Bexio Client Bug**: Fixed constructor mismatch that prevented custom `default_vat_rate` and caused dashboard crashes.
- **SQLite Compatibility**: Added datetime adapters/converters for proper Python 3.12+ support.
- **Build System**: Corrected `uv_build` version range in `pyproject.toml`.
- **Tests**: Refactored `test_db.py` and `test_models.py` into proper pytest functions.

## [0.1.1] - 2024-03-24

### Added
- HTTP Basic Authentication to the server dashboard for secure access.
- SQLite database migrations for expanded stats features.
- Stats Dashboard showing total booked amounts and top merchants.
- `CHANGELOG.md` file for version tracking.

### Changed
- `extraction.py` now leverages HTTP timeout handling and proper retry decorators.
- `models.py` normalcy normalization for merchant names.
- Database connection defaults to WAL journaling mode.

### Fixed
- Fixed `owner_id` logic to fetch from `company_profile` instead of `user_id`.
- Fixed `None` date crash in `validation.py`.

## [0.1.0] - 2024-01-15

### Added
- Initial release with core ingestion pipeline (Watcher, Email).
- Basic PaddleOCR integration and OpenAI extraction.
- Minimal Review Dashboard.
