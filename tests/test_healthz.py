import pytest
from httpx import AsyncClient, ASGITransport
from bexio_receipts.server import app


@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/healthz")
        # should fail since bexio is missing
        assert response.status_code == 503
        assert response.json()["db"] == "ok"
