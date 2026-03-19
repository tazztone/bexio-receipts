import pytest
from httpx import AsyncClient, ASGITransport
from bexio_receipts.server import app, get_settings

@pytest.mark.asyncio
async def test_metrics(test_settings):
    # Override settings to use test credentials
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    auth = ("admin", test_settings.review_password)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/metrics", auth=auth)
        assert response.status_code == 200
        content = response.text
        assert "receipts_processed_total" in content
        assert "receipts_failed_total" in content
        assert "ocr_confidence_avg" in content
    
    app.dependency_overrides.clear()
