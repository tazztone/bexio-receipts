import base64
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from bexio_receipts.server import app, get_settings


@pytest.mark.asyncio
async def test_rate_limit(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Reset limiter state so previous tests don't pre-exhaust the quota.
    try:
        app.state.limiter.reset()
    except Exception:
        pass

    # Pin remote address to a constant IP so all requests share the same bucket.
    with patch("bexio_receipts.server.get_remote_address", return_value="192.0.2.1"):
        bad_auth = base64.b64encode(b"admin:bad_password").decode()
        bad_headers = {"Authorization": f"Basic {bad_auth}"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            responses = []
            for _ in range(10):
                responses.append(await ac.get("/", headers=bad_headers))

            # At least one request after the 5th must be rate-limited.
            assert any(r.status_code == 429 for r in responses)

            # Successful auth is never rate-limited.
            good_auth = base64.b64encode(b"admin:test_password").decode()
            good_headers = {"Authorization": f"Basic {good_auth}"}
            for _ in range(10):
                r = await ac.get("/", headers=good_headers)
                assert r.status_code == 200

    app.dependency_overrides.clear()
