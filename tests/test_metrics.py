import pytest
from httpx import AsyncClient, ASGITransport
from bexio_receipts.server import app

@pytest.mark.asyncio
async def test_metrics():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/metrics")
        assert response.status_code == 200
        content = response.text
        assert "receipts_processed_total" in content
        assert "receipts_failed_total" in content
        assert "ocr_confidence_avg" in content
