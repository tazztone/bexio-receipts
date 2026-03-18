import pytest
import os
from unittest.mock import AsyncMock, patch
from bexio_receipts.pipeline import process_receipt
from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector
from bexio_receipts.models import Receipt
from datetime import date

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    return DuplicateDetector(str(db_path))

@pytest.mark.asyncio
async def test_process_receipt_duplicate(mock_db, tmp_path):
    # Create dummy file
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    # Mark as duplicate
    file_hash = mock_db.get_hash(str(test_file))
    mock_db.mark_processed(file_hash, str(test_file), "123")

    settings = Settings(bexio_api_token="test")
    bexio_client = AsyncMock()

    result = await process_receipt(str(test_file), settings, bexio_client, mock_db)
    assert result["status"] == "duplicate"
    assert result["expense_id"] == "123"

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_success(mock_extract, mock_ocr, mock_db, tmp_path):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    settings = Settings(
        bexio_api_token="test",
        default_booking_account_id=1,
        default_bank_account_id=2
    )
    bexio_client = AsyncMock()
    bexio_client.upload_file.return_value = "file-uuid"
    bexio_client.create_purchase_bill.return_value = {"id": 100}

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = Receipt(
        merchant_name="Migros",
        date=date.today(),
        total_incl_vat=10.0
    )

    result = await process_receipt(str(test_file), settings, bexio_client, mock_db)
    assert result["status"] == "booked"
    assert result["expense_id"] == 100

    # Check DB was updated with stats
    stats = mock_db.get_stats()
    assert stats["total_processed"] == 1
    assert stats["total_booked"] == 10.0
