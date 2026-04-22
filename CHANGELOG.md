# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-04-22

### Added
- **Multi-language Vision Prompts**: Added full support for French (`fr`) prompt
  templates in the Vision pipeline, joining German and English.
- **Drift-proof Prompt Generation**: System prompts are now generated
  dynamically from the `VisionExtraction` Pydantic model. This guarantees that
  the VLM always receives the most up-to-date schema.
- **Vision Pipeline Documentation**: Added comprehensive descriptions to extraction
  quality metrics (formerly `confidence`) to clarify the heuristic differences
  between Vision and OCR modes.

### Fixed
- **Circular Dependency Resolution**: Refactored the core data models to break a
  circular import between `document_processor` and `prompts`. `VisionExtraction`
  now resides in `models.py`.
- **Processor Safety**: Hardened `get_processor` with explicit validation and
  error handling for unknown processor modes.
- **Code Quality**: Fixed several nested control flow lints (SIM117, SIM102) and
  cleaned up the global Ruff configuration.

## [0.2.0] - 2026-04-19

### Fixed
- **VAT Mathematics and Assignment Checks**: Modified `resolve_vat_rows` to guarantee correct assignments when third VAT column is missing (identifying the smaller value as VAT vs Base), preventing silent validation failures. Added validation that guarantees if total amount is present, VAT entries must also exist. Errors now cascade properly as `ExtractionError` for review.

### Added
- **Per-Line Account Mapping**: The review dashboard now supports mapping distinct accounting (SOLL) accounts to individual VAT line items on a single receipt.
- **HABEN Payment Toggles**: Added support for differentiating Bank vs Cash (HABEN) payments for expenses, complete with intelligent auto-selection based on receipt payment method (e.g. "Zahlungsart: Bar").
- **Premium UI Overhaul**: Redesigned the entire web dashboard with a custom dark theme, glassmorphism, modern typography (Outfit), and unified status badges across all templates.
- **Smart PDF Extraction**: Replaced OCR dependency for digital PDFs with native text extraction via `pdfplumber`, guaranteeing 100% text fidelity and bypassing vision models entirely.
- **VAT Breakdown Extraction**: Pydantic and GLM-OCR prompts now natively extract multi-rate VAT data (`vat_breakdown` arrays) from receipts like Coop or Migros.
- **Offline Development Mode**: Introduced `OFFLINE_MODE` config flag, allowing local execution and UI testing without needing a valid Bexio Personal Access Token.
- **Resilience Testing**: Added `test_resilience.py` mock suite.

### Maintenance
- **Dependency Refresh**: Updated all core and dev dependencies to their latest versions, including `ruff` (v0.15.11), `mypy` (v1.20.1), `pydantic-ai` (v1.84.1), and `typer` (v0.24.1).
- **Test Hardening**: Improved test isolation by fixing model overrides in `conftest.py` and aligning mocks with implementation changes in `BexioClient`.
- **Pre-commit Integration**: Formally added `pre-commit` to the development workflow with automated `ruff` and `mypy` hooks.

### Fixed
- **Hardened OCR Extraction**: Addressed severe `GLM-OCR` hallucination issues (swapped VAT numbers, incorrect merchants) by simplifying the vision prompt to raw text output and offloading structured extraction to the secondary LLM.
- **Bexio `item_net` Correctness**: `create_purchase_bill` now sends net amounts and instructs Bexio to apply VAT mathematically (`item_net=True`), preventing double-taxation bugs.
- **Startup Resilience**: The CLI `process`, `reprocess`, and `watcher` commands no longer crash on boot if the Bexio API is unreachable or the token is invalid.
- **First-Run Configuration**: The `bexio-receipts init` wizard now correctly injects `REVIEW_USERNAME` and `REVIEW_PASSWORD`, preventing immediate HTTP 401 lockouts on fresh installations.
- **API Correctness**: Standardized around the `/3.0/users/me` endpoint.

## [0.1.3] - 2024-06-20

### Added
- **New Documentation Suite**: Added `CONFIGURATION.md`, `TROUBLESHOOTING.md`, `OPERATIONS.md`, and `DECISIONS.md`.
- **Project Standards**: Added `LICENSE`, `SECURITY.md`, and GitHub Issue Templates.
- **Visuals**: Integrated Mermaid diagrams and high-level architecture maps.

### Changed
- **Archive Consolidation**: Migrated strategic takeaways from `docs/archive/` into normative documentation.
- **Model Standard**: Standardized on `qwen3.5:9b` as the project default.

### Fixed
- **Documentation Errors**: Corrected broken `uv` install links and stale model references.
- **Security**: Added real vulnerability reporting guidelines.

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
- Basic PaddleOCR integration and structured extraction.
- Minimal Review Dashboard.
