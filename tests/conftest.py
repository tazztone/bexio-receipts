import os

# Set required environment variables before importing any app modules
# to prevent Pydantic ValidationError on startup during testing.
os.environ["BEXIO_API_TOKEN"] = "dummy_token_for_tests"
os.environ["REVIEW_PASSWORD"] = "dummy_password_for_tests"
os.environ["SECRET_KEY"] = "dummy_secret_key_for_tests"
os.environ["DEFAULT_BOOKING_ACCOUNT_ID"] = "1"
os.environ["DEFAULT_BANK_ACCOUNT_ID"] = "2"

import pytest
from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector


@pytest.fixture
def test_settings():
    return Settings(
        bexio_api_token="test_token",
        review_password="test_password",
        secret_key="test_secret_key",
        default_booking_account_id=1,
        default_bank_account_id=2,
        ocr_engine="paddleocr",
    )


@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    return DuplicateDetector(str(db_path))
