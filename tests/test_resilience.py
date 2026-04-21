import tempfile

import httpx
import pytest

from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector
from bexio_receipts.document_processor import ProcessingResult
from bexio_receipts.pipeline import process_receipt


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

        with (
            patch("bexio_receipts.pipeline.get_processor") as mock_get_processor,
        ):
            from datetime import date

            from bexio_receipts.extraction import ExtractionTrace

            mock_processor = AsyncMock()
            mock_get_processor.return_value = mock_processor
            mock_processor.process.return_value = ProcessingResult(
                raw_text="extracted text",
                merchant_name="Test",
                transaction_date=date.today().isoformat(),
                total_incl_vat=10.0,
                confidence=0.9,
                trace=ExtractionTrace(),
            )

            # Mock upload_file to fail (simulating no connectivity)
            mock_bexio.upload_file.side_effect = Exception("No connectivity")

            result = await process_receipt(
                str(receipt_path), mock_settings, mock_bexio, temp_db
            )

            # Should fallback to review instead of crashing
            assert result["status"] == "review"
            assert "review_file" in result


@pytest.mark.asyncio
async def test_push_safety_gate_pipeline(mock_settings, temp_db, tmp_path):
    # Setup: BEXIO_PUSH_ENABLED=False (default)
    mock_settings.bexio_push_enabled = False

    receipt_path = tmp_path / "safety_test.png"
    receipt_path.write_text("content")

    from unittest.mock import AsyncMock, patch

    mock_bexio = AsyncMock(spec=BexioClient)

    with tempfile.TemporaryDirectory() as review_dir:
        mock_settings.review_dir = review_dir
        with (
            patch("bexio_receipts.pipeline.get_processor") as mock_get_processor,
        ):
            from datetime import date

            from bexio_receipts.extraction import ExtractionTrace

            mock_processor = AsyncMock()
            mock_get_processor.return_value = mock_processor
            mock_processor.process.return_value = ProcessingResult(
                raw_text="text",
                merchant_name="T",
                transaction_date=date.today().isoformat(),
                total_incl_vat=1.0,
                confidence=0.9,
                trace=ExtractionTrace(),
            )

            result = await process_receipt(
                str(receipt_path), mock_settings, mock_bexio, temp_db
            )

            assert result["status"] == "review"
            # Check that failed_stage is safety_gate
            import json

            with open(result["review_file"]) as f:
                review_data = json.load(f)
                assert review_data["failed_stage"] == "safety_gate"

            # Verify no write calls were made
            assert mock_bexio.upload_file.call_count == 0
            assert mock_bexio.create_purchase_bill.call_count == 0


def test_cli_push_gate_hierarchy():
    from unittest.mock import patch

    from typer.testing import CliRunner

    from bexio_receipts.cli import app

    runner = CliRunner()

    # Mock settings to have PUSH_ENABLED=False
    with patch("bexio_receipts.cli.get_settings") as mock_get_settings:
        from bexio_receipts.config import Settings

        mock_get_settings.return_value = Settings(
            bexio_push_enabled=False, review_password="admin", secret_key="test"
        )

        # Create dummy file
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            # Run 'process --push'
            result = runner.invoke(app, ["process", tmp.name, "--push"])

            assert result.exit_code == 1
            assert "BEXIO_PUSH_ENABLED=false" in result.stdout

            # Run 'reprocess --push'
            with tempfile.NamedTemporaryFile(suffix=".json") as tmp_json:
                tmp_json.write(b'{"original_file": "exists"}')
                tmp_json.flush()
                with patch("pathlib.Path.exists", return_value=True):
                    result = runner.invoke(app, ["reprocess", tmp_json.name, "--push"])
                    assert result.exit_code == 1
                    assert "BEXIO_PUSH_ENABLED=false" in result.stdout
