import pytest
from httpx import AsyncClient, ASGITransport
import base64
from bexio_receipts.server import app, get_settings


@pytest.mark.asyncio
async def test_rate_limit(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Try bad password
    auth = base64.b64encode(b"admin:bad").decode()
    headers = {"Authorization": f"Basic {auth}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        for i in range(5):
            response = await ac.get("/", headers=headers)
            assert response.status_code == 401

        # 6th request should fail with 429 Too Many Requests
        response = await ac.get("/", headers=headers)
        assert response.status_code == 429

        # Test success isn't rate limited
        good_auth = base64.b64encode(
            f"admin:{test_settings.review_password}".encode()
        ).decode()
        good_headers = {"Authorization": f"Basic {good_auth}"}

        for i in range(10):
            response = await ac.get("/", headers=good_headers)
            assert response.status_code == 200
