import pytest
from unittest.mock import AsyncMock, patch
from bexio_receipts.pipeline import process_receipt
from bexio_receipts.database import DuplicateDetector
from bexio_receipts.models import Receipt
from datetime import date

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    return DuplicateDetector(str(db_path))

@pytest.mark.asyncio
async def test_process_receipt_duplicate(mock_db, tmp_path, test_settings):
    # Create dummy file
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    # Mark as duplicate
    file_hash = mock_db.get_hash(str(test_file))
    mock_db.mark_processed(file_hash, str(test_file), "123")

    bexio_client = AsyncMock()

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "duplicate"
    assert result["expense_id"] == "123"

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_success(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.return_value = "file-uuid"
    bexio_client.create_purchase_bill.return_value = {"id": 100}

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = Receipt(
        merchant_name="Migros",
        date=date.today(),
        total_incl_vat=10.0
    )

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "booked"
    assert result["expense_id"] == 100

    # Check DB was updated with stats
    stats = mock_db.get_stats()
    assert stats["total_processed"] == 1
    assert stats["total_booked"] == 10.0

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
async def test_process_receipt_low_confidence(mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()

    mock_ocr.return_value = ("Test Text", 0.5, None)

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_extraction_failed(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.side_effect = Exception("Extraction failed")

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_validation_failed(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = Receipt(
        merchant_name="Migros",
        date=date.today(),
        total_incl_vat=-10.0 # triggers validation error
    )

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_no_merchant(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.return_value = "file-uuid"
    bexio_client.create_expense.return_value = {"id": 200}

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = Receipt(
        merchant_name=None,
        date=date.today(),
        total_incl_vat=10.0
    )

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "booked"
    assert result["expense_id"] == 200

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_file_not_found(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    bexio_client = AsyncMock()
    with pytest.raises(FileNotFoundError):
        await process_receipt(str(tmp_path / "nonexistent.png"), test_settings, bexio_client, mock_db)

@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_bexio_error(mock_extract, mock_ocr, mock_db, tmp_path, test_settings):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.side_effect = Exception("API down")

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = Receipt(
        merchant_name="Migros",
        date=date.today(),
        total_incl_vat=10.0
    )

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review_failed" or result["status"] == "review"
