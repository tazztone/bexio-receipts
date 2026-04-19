import pytest
import httpx
from bexio_receipts.config import Settings
from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.pipeline import process_receipt
from bexio_receipts.database import DuplicateDetector
import tempfile


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        yield DuplicateDetector(f.name)


@pytest.fixture
def mock_settings():
    return Settings(
        offline_mode=True,
        bexio_api_token="dummy",
        default_booking_account_id=0,
        default_bank_account_id=0,
        review_password="admin",
    )


@pytest.mark.asyncio
async def test_offline_mode_settings(mock_settings):
    # Settings should initialize without errors when offline_mode=True
    assert mock_settings.offline_mode is True


@pytest.mark.asyncio
async def test_cache_lookups_resilience(respx_mock):
    # Mock Bexio API to return 401
    respx_mock.get("https://api.bexio.com/3.0/users/me").mock(
        return_value=httpx.Response(401)
    )
    respx_mock.get("https://api.bexio.com/3.0/taxes").mock(
        return_value=httpx.Response(401)
    )
    respx_mock.get("https://api.bexio.com/2.0/accounts").mock(
        return_value=httpx.Response(401)
    )

    async with BexioClient(token="dummy") as client:
        # This should NOT raise an exception
        await client.cache_lookups()

        # Caches should just be empty/none
        assert client._user_id is None
        assert not client._tax_cache
        assert not client._account_cache


@pytest.mark.asyncio
async def test_full_pipeline_offline(mock_settings, temp_db, tmp_path):
    # Create a dummy receipt
    receipt_path = tmp_path / "offline_receipt.png"
    receipt_path.write_text("dummy image content")

    # Mock BexioClient to avoid real API calls
    from unittest.mock import AsyncMock

    mock_bexio = AsyncMock(spec=BexioClient)

    # Run process_receipt with offline_mode=True
    # It should succeed (status='review') even if BexioClient would fail if called
    with tempfile.TemporaryDirectory() as review_dir:
        mock_settings.review_dir = review_dir

        from unittest.mock import patch

        with patch(
            "bexio_receipts.pipeline.async_run_ocr",
            return_value=("extracted text", 0.9, []),
        ):
            from bexio_receipts.models import Receipt
            from datetime import date

            with patch(
                "bexio_receipts.pipeline.extract_receipt",
                return_value=Receipt(
                    merchant_name="Test",
                    total_incl_vat=10.0,
                    transaction_date=date.today(),
                ),
            ):
                # Mock upload_file to fail (simulating no connectivity)
                mock_bexio.upload_file.side_effect = Exception("No connectivity")

                result = await process_receipt(
                    str(receipt_path), mock_settings, mock_bexio, temp_db
                )

                # Should fallback to review instead of crashing
                assert result["status"] == "review"
                assert "review_file" in result
