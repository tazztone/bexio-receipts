import pytest
from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.models import Receipt
from datetime import date
import httpx
import respx


@pytest.mark.asyncio
@respx.mock
async def test_bexio_cache_lookups():
    # Setup mocks
    respx.get("https://api.bexio.com/2.0/company_profile").mock(
        return_value=httpx.Response(200, json={"owner_id": 2})
    )
    respx.get("https://api.bexio.com/3.0/users/me").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Test User"})
    )
    respx.get("https://api.bexio.com/3.0/taxes").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "value": 8.1}, {"id": 2, "value": 2.6}]
        )
    )
    respx.get("https://api.bexio.com/2.0/accounts").mock(
        return_value=httpx.Response(200, json=[{"id": 100, "account_no": "6000"}])
    )

    async with BexioClient(token="test") as client:
        await client.cache_lookups()

        assert client._user_id == 1
        assert client._owner_id == 2
        assert client._tax_cache[8.1] == 1
        assert client._account_cache["6000"] == 100


@pytest.mark.asyncio
@respx.mock
async def test_create_expense():
    expense_route = respx.post("https://api.bexio.com/4.0/expenses").mock(
        return_value=httpx.Response(200, json={"id": 999})
    )

    async with BexioClient(token="test") as client:
        client._tax_cache[8.1] = 1

        receipt = Receipt(
            merchant_name="Test Store",
            date=date(2023, 1, 1),
            total_incl_vat=10.50,
            vat_rate_pct=8.1,
        )

        expense = await client.create_expense(receipt, "file-uuid", 100, 200)

        assert expense["id"] == 999
        # Check payload
        assert expense_route.called
        request = expense_route.calls.last.request
        import json

        payload = json.loads(request.content)
        assert payload["title"] == "Test Store"
        assert payload["paid_on"] == "2023-01-01"
        assert payload["amount"] == 10.50
        assert payload["tax_id"] == 1
        assert payload["booking_account_id"] == 100
        assert payload["bank_account_id"] == 200
        assert payload["attachment_ids"] == ["file-uuid"]
