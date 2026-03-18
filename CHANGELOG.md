# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2024-05-24

### Added
- HTTP Basic Authentication to the server dashboard for secure access.
- SQLite database migrations for expanded stats features (stores financial values such as total booked and reclaimed VAT amounts).
- Pipeline now tracks new financial values such as `total_incl_vat` and `vat_amount` per processed receipt.
- Stats Dashboard now calculates actual total booked amounts, total VAT reclaimed, and displays a list of the top 5 merchants.
- `CHANGELOG.md` file for version tracking.
- Test coverage for the integration of `pipeline` and `server` logic.

### Changed
- `extraction.py` now leverages HTTP timeout handling and proper retry decorators for robustness during LLM extraction.
- `models.py` uses `field_validator` on `merchant_name` to consistently normalize data to title casing and removes common legal suffixes to avoid duplicates.
- Database connection defaults to WAL journaling mode with timeout pooling for handling multithreaded operations correctly.
- `push_to_bexio` server route now correctly infers file types (e.g., pdf or image types) using `mimetypes` instead of hardcoding `image/png`.

### Fixed
- Fixed an issue in `bexio_client.py` where the API caller `user_id` was erroneously used as the `owner_id` for creating contacts. It now fetches the correct main tenant owner from Bexio via `company_profile`.
- Fixed a bug where a `None` date would cause a `TypeError` crash in `validation.py`.
