from datetime import date

import httpx
import pytest
import respx

from bexio_receipts.bexio_client import BexioClient, is_retryable_exception
from bexio_receipts.models import Receipt


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


from unittest.mock import patch

@pytest.mark.asyncio
@respx.mock
async def test_bexio_cache_lookups_get_profile_error():
    # Setup mocks for taxes and accounts to ensure the flow continues
    respx.get("https://api.bexio.com/3.0/taxes").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "value": 8.1}, {"id": 2, "value": 2.6}]
        )
    )
    respx.get("https://api.bexio.com/2.0/accounts").mock(
        return_value=httpx.Response(200, json=[{"id": 100, "account_no": "6000"}])
    )

    with patch(
        "bexio_receipts.bexio_client.BexioClient.get_profile",
        side_effect=Exception("Simulated API failure"),
    ), patch("bexio_receipts.bexio_client.logger") as mock_logger:

        async with BexioClient(token="test") as client:
            await client.cache_lookups()

            # Check that get_profile failure was logged and handled gracefully
            assert client._user_id is None
            mock_logger.warning.assert_any_call(
                "Failed to fetch user profile in cache_lookups", error="Simulated API failure"
            )

            # Verify that execution continued and other caches were populated
            assert client._tax_cache[8.1] == 1
            assert client._account_cache["6000"] == 100


@pytest.mark.asyncio
@respx.mock
async def test_create_expense():
    expense_route = respx.post("https://api.bexio.com/4.0/expenses").mock(
        return_value=httpx.Response(200, json={"id": 999})
    )

    async with BexioClient(token="test", push_enabled=True) as client:
        client._tax_cache[8.1] = 1

        receipt = Receipt(
            merchant_name="Test Store",
            transaction_date=date(2023, 1, 1),
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


@pytest.mark.asyncio
@respx.mock
async def test_create_purchase_bill_net_fallback():
    bill_route = respx.post("https://api.bexio.com/4.0/purchase/bills").mock(
        return_value=httpx.Response(200, json={"id": 888})
    )

    async with BexioClient(token="test", push_enabled=True) as client:
        client._tax_cache[8.1] = 1
        client._tax_cache[2.6] = 2

        # Mock contact search (POST to /2.0/contact/search)
        respx.post("https://api.bexio.com/2.0/contact/search").mock(
            return_value=httpx.Response(200, json=[{"id": 50}])
        )

        # Case 1: vat_amount is None, vat_rate_pct is 8.1
        # Gross 214.20 / 1.081 = 198.15 net
        receipt = Receipt(
            merchant_name="Prodega",
            transaction_date=date(2026, 1, 31),
            total_incl_vat=214.20,
            vat_rate_pct=8.1,
            vat_amount=None,  # Crucial for test
        )

        await client.create_purchase_bill(receipt, "uuid", [100])
        payload = bill_route.calls.last.request.read()
        import json

        data = json.loads(payload)
        assert data["item_net"] is True
        assert data["line_items"][0]["amount"] == 198.15

        # Case 2: Both vat_amount and vat_rate_pct are None (fallback to default 8.1)
        receipt_no_rate = Receipt(
            merchant_name="Prodega",
            transaction_date=date(2026, 1, 31),
            total_incl_vat=214.20,
            vat_rate_pct=None,
            vat_amount=None,
        )
        await client.create_purchase_bill(receipt_no_rate, "uuid", [100])
        data = json.loads(bill_route.calls.last.request.read())
        assert data["line_items"][0]["amount"] == 198.15


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (429, True),
        (500, True),
        (503, True),
        (599, True),
        (400, False),
        (404, False),
    ],
)
def test_is_retryable_exception_http_status_error(status_code, expected):
    request = httpx.Request("GET", "https://api.bexio.com")
    response = httpx.Response(status_code, request=request)
    exception = httpx.HTTPStatusError("Error", request=request, response=response)
    assert is_retryable_exception(exception) is expected


@pytest.mark.parametrize(
    "exception, expected",
    [
        (ValueError("Some error"), False),
        (httpx.RequestError("Request error", request=httpx.Request("GET", "https://api.bexio.com")), False),
        (Exception("General error"), False),
    ],
)
def test_is_retryable_exception_other_errors(exception, expected):
    assert is_retryable_exception(exception) is expected


@pytest.mark.asyncio
@respx.mock
async def test_bexio_cache_lookups_fetch_taxes_error():
    # Setup mocks
    respx.get("https://api.bexio.com/2.0/company_profile").mock(
        return_value=httpx.Response(200, json={"owner_id": 2})
    )
    respx.get("https://api.bexio.com/3.0/users/me").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Test User"})
    )
    # Mock taxes to fail
    respx.get("https://api.bexio.com/3.0/taxes").mock(
        return_value=httpx.Response(400, json={"error": "Bad Request"})
    )
    respx.get("https://api.bexio.com/2.0/accounts").mock(
        return_value=httpx.Response(200, json=[{"id": 100, "account_no": "6000"}])
    )

    async with BexioClient(token="test") as client:
        await client.cache_lookups()

        assert client._user_id == 1
        assert client._owner_id == 2
        # Tax cache should remain empty because fetch_taxes failed
        assert not client._tax_cache
        # But execution should continue and fetch accounts
        assert client._account_cache["6000"] == 100
