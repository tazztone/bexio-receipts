from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bexio_receipts.database import DuplicateDetector
from bexio_receipts.models import Receipt
from bexio_receipts.pipeline import (
    decide_bexio_action,
    process_receipt,
    send_to_review,
)


def test_decide_bexio_action():
    from bexio_receipts.models import VatEntry

    # Case 1: Merchant name present -> purchase_bill
    r1 = Receipt(merchant_name="Migros")
    assert decide_bexio_action(r1) == "purchase_bill"

    # Case 2: Multi-VAT -> purchase_bill
    r2 = Receipt(
        vat_breakdown=[
            VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1),
            VatEntry(rate=2.6, base_amount=50.0, vat_amount=1.3),
        ]
    )
    assert decide_bexio_action(r2) == "purchase_bill"

    # Case 3: No merchant, single VAT -> expense
    r3 = Receipt(vat_breakdown=[VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1)])
    assert decide_bexio_action(r3) == "expense"

    # Case 4: No merchant, no VAT -> expense
    r4 = Receipt()
    assert decide_bexio_action(r4) == "expense"


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
async def test_process_receipt_success(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.return_value = "file-uuid"
    bexio_client.create_purchase_bill.return_value = {"id": 100}

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = (Receipt(
        merchant_name="Migros", transaction_date=date.today(), total_incl_vat=10.0
    ), "raw")

    result = await process_receipt(
        str(test_file), test_settings, bexio_client, mock_db, push_confirmed=True
    )
    assert result["status"] == "booked"
    assert result["expense_id"] == 100

    # Check DB was updated with stats
    stats = mock_db.get_stats()
    assert stats["total_processed"] == 1
    assert stats["total_booked"] == 10.0


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
async def test_process_receipt_low_confidence(
    mock_ocr, mock_db, tmp_path, test_settings
):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()

    mock_ocr.return_value = ("Test Text", 0.5, None)

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_extraction_failed(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
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
async def test_process_receipt_validation_failed(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = (Receipt(
        merchant_name="Migros",
        transaction_date=date.today(),
        total_incl_vat=-10.0,  # triggers validation error
    ), "raw")

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_no_merchant(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.return_value = "file-uuid"
    bexio_client.create_expense.return_value = {"id": 200}

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = (Receipt(
        merchant_name=None, transaction_date=date.today(), total_incl_vat=10.0
    ), "raw")

    result = await process_receipt(
        str(test_file), test_settings, bexio_client, mock_db, push_confirmed=True
    )
    assert result["status"] == "booked"
    assert result["expense_id"] == 200


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_file_not_found(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
    bexio_client = AsyncMock()
    result = await process_receipt(
        str(tmp_path / "nonexistent.png"), test_settings, bexio_client, mock_db
    )
    assert result["status"] == "error"
    assert "File not found" in result["message"]


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
@patch("bexio_receipts.pipeline.extract_receipt")
async def test_process_receipt_bexio_error(
    mock_extract, mock_ocr, mock_db, tmp_path, test_settings
):
    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    bexio_client = AsyncMock()
    bexio_client.upload_file.side_effect = Exception("API down")

    mock_ocr.return_value = ("Test Text", 0.95, None)
    mock_extract.return_value = (Receipt(
        merchant_name="Migros", transaction_date=date.today(), total_incl_vat=10.0
    ), "raw")

    result = await process_receipt(
        str(test_file), test_settings, bexio_client, mock_db, push_confirmed=True
    )
    assert result["status"] in ["review", "review_failed"]


@pytest.mark.asyncio
async def test_send_to_review(tmp_path, test_settings):
    review_dir = tmp_path / "review_queue"
    test_settings.review_dir = str(review_dir)

    test_file = tmp_path / "orig.png"
    test_file.write_text("img")

    receipt = Receipt(merchant_name="Migros", total_incl_vat=10.0)

    result = await send_to_review(
        str(test_file), "raw text", ["error 1"], test_settings, receipt
    )
    assert result["status"] == "review"
    assert Path(result["review_file"]).exists()

    # Test fallback
    with patch("pathlib.Path.mkdir", side_effect=Exception("Perm error")):
        result = await send_to_review(
            str(test_file), "raw text", ["error 1"], test_settings, receipt
        )
        assert result["status"] == "review_failed"


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
async def test_process_receipt_unsupported_mime(mock_ocr, tmp_path, test_settings, mock_db):
    import json
    from PIL import UnidentifiedImageError

    test_file = tmp_path / "test.txt"
    test_file.write_text("unsupported")

    bexio_client = AsyncMock()
    mock_ocr.side_effect = Exception("cannot identify image file")

    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"

    with open(result["review_file"]) as f:
        review_data = json.load(f)
        assert "cannot identify image file" in review_data["errors"][0]


@pytest.mark.asyncio
@patch("bexio_receipts.pipeline.async_run_ocr")
async def test_process_receipt_ocr_timeout(mock_ocr, tmp_path, test_settings, mock_db):
    import json

    test_file = tmp_path / "test.png"
    test_file.write_text("dummy")

    mock_ocr.side_effect = TimeoutError()

    bexio_client = AsyncMock()
    result = await process_receipt(str(test_file), test_settings, bexio_client, mock_db)
    assert result["status"] == "review"

    with open(result["review_file"]) as f:
        review_data = json.load(f)
        assert "OCR stage timed out" in review_data["errors"][0]
