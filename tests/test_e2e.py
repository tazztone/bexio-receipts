from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector
from bexio_receipts.document_processor import ProcessingResult
from bexio_receipts.extraction import ExtractionTrace
from bexio_receipts.pipeline import process_receipt


@pytest.mark.asyncio
@respx.mock
async def test_pipeline_e2e(tmp_path):
    settings = Settings(
        env="test",
        bexio_api_token="dummy",
        review_password="dummy",
        default_booking_account_id=100,
        default_bank_account_id=200,
        database_path=str(tmp_path / "test.db"),
        review_dir=str(tmp_path / "review"),
        bexio_push_enabled=True,
    )

    db = DuplicateDetector(settings.database_path)

    respx.get("https://api.bexio.com/2.0/company_profile").mock(
        return_value=httpx.Response(200, json={"owner_id": 2})
    )
    respx.get("https://api.bexio.com/3.0/profile/me").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Test"})
    )
    respx.get("https://api.bexio.com/3.0/taxes").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "value": 8.1}])
    )
    respx.get("https://api.bexio.com/2.0/accounts").mock(
        return_value=httpx.Response(200, json=[{"id": 100, "account_no": "6000"}])
    )

    respx.post("https://api.bexio.com/3.0/files").mock(
        return_value=httpx.Response(200, json={"id": "file-123", "name": "dummy.png"})
    )

    respx.post("https://api.bexio.com/2.0/contact/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.post("https://api.bexio.com/2.0/contact").mock(
        return_value=httpx.Response(200, json={"id": 555})
    )
    expense_route = respx.post("https://api.bexio.com/4.0/purchase/bills").mock(
        return_value=httpx.Response(200, json={"id": 999})
    )

    dummy_file = tmp_path / "dummy.png"
    dummy_file.touch()

    with (
        patch("bexio_receipts.pipeline.get_processor") as mock_get_processor,
    ):
        mock_processor = AsyncMock()
        mock_get_processor.return_value = mock_processor
        mock_processor.process.return_value = ProcessingResult(
            raw_text="Test Text",
            merchant_name="COOP",
            transaction_date=date.today().isoformat(),
            total_incl_vat=10.80,
            currency="CHF",
            confidence=0.95,
            trace=ExtractionTrace(),
            account_assignments=[],
        )

        async with BexioClient("dummy", push_enabled=True) as client:
            await client.cache_lookups()
            result = await process_receipt(
                str(dummy_file), settings, client, db, push_confirmed=True
            )

    assert result["status"] == "booked"
    assert str(result["expense_id"]) == "999"
    assert expense_route.called
    assert db.is_duplicate(db.get_hash(str(dummy_file))) == "999"
