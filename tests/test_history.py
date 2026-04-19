import pytest
import base64
from httpx import AsyncClient, ASGITransport
from bexio_receipts.server import app, get_settings, get_db
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_history_view(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings

    mock_db = MagicMock()
    # Mock return value for get_processed_receipts
    mock_db.get_processed_receipts.return_value = [
        {
            "file_hash": "hash1",
            "file_path": "test1.png",
            "processed_at": None,
            "bexio_id": "123",
            "total": 10.5,
            "merchant": "Merchant 1",
            "vat": 0.8,
            "confidence": 0.95,
        }
    ]
    mock_db.get_total_processed_count.return_value = 1
    app.dependency_overrides[get_db] = lambda: mock_db

    auth = base64.b64encode(b"admin:test_password").decode()
    headers = {"Authorization": f"Basic {auth}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/history", headers=headers)
        assert response.status_code == 200
        assert "Merchant 1" in response.text
        assert "10.5 CHF" in response.text
        assert "123" in response.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_history_search(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings

    mock_db = MagicMock()
    mock_db.get_processed_receipts.return_value = []
    mock_db.get_total_processed_count.return_value = 0
    app.dependency_overrides[get_db] = lambda: mock_db

    auth = base64.b64encode(b"admin:test_password").decode()
    headers = {"Authorization": f"Basic {auth}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/history?search=UnknownMerchant", headers=headers)
        assert response.status_code == 200
        assert "No processed receipts found" in response.text
        mock_db.get_processed_receipts.assert_called_with(
            limit=25, offset=0, search="UnknownMerchant"
        )

    app.dependency_overrides.clear()
