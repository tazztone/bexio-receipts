import pytest
from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector

@pytest.fixture
def test_settings():
    return Settings(
        bexio_api_token="test_token",
        review_password="test_password",
        default_booking_account_id=1,
        default_bank_account_id=2,
        ocr_engine="paddleocr"
    )

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    return DuplicateDetector(str(db_path))
