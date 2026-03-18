import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.models import Receipt
from datetime import date
import httpx

@pytest.mark.asyncio
async def test_bexio_cache_lookups():
    async with BexioClient(token="test") as client:
        # Mocking httpx responses
        mock_resp_profile = MagicMock()
        mock_resp_profile.json.return_value = {"id": 1, "name": "Test User"}
        mock_resp_profile.raise_for_status = MagicMock()

        mock_resp_taxes = MagicMock()
        mock_resp_taxes.json.return_value = [{"id": 1, "value": "8.1"}, {"id": 2, "value": "2.6"}]
        mock_resp_taxes.raise_for_status = MagicMock()

        mock_resp_accounts = MagicMock()
        mock_resp_accounts.json.return_value = [{"id": 100, "account_no": "6000"}]
        mock_resp_accounts.raise_for_status = MagicMock()

        mock_resp_comp = MagicMock()
        mock_resp_comp.json.return_value = {"owner_id": 2}
        mock_resp_comp.raise_for_status = MagicMock()

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = [mock_resp_profile, mock_resp_comp, mock_resp_taxes, mock_resp_accounts]

            await client.cache_lookups()
            
            assert client._user_id == 1
            assert client._owner_id == 2
            assert client._tax_cache[8.1] == 1
            assert client._account_cache["6000"] == 100
            assert mock_get.call_count == 4

@pytest.mark.asyncio
async def test_create_expense():
    async with BexioClient(token="test") as client:
        client._tax_cache[8.1] = 1
        
        receipt = Receipt(
            merchant_name="Test Store",
            date=date(2023, 1, 1),
            total_incl_vat=10.50,
            vat_rate_pct=8.1
        )
        
        mock_resp_expense = MagicMock()
        mock_resp_expense.json.return_value = {"id": 999}
        mock_resp_expense.raise_for_status = MagicMock()
        
        with patch.object(httpx.AsyncClient, "post") as mock_post:
            mock_post.return_value = mock_resp_expense
            
            expense = await client.create_expense(receipt, "file-uuid", 100, 200)
            
            assert expense["id"] == 999
            # Check payload
            args, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["title"] == "Test Store"
            assert payload["paid_on"] == "2023-01-01"
            assert payload["amount"] == 10.50
            assert payload["tax_id"] == 1
            assert payload["booking_account_id"] == 100
            assert payload["bank_account_id"] == 200
            assert payload["attachment_ids"] == ["file-uuid"]
