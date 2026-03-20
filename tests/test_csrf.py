import pytest
from httpx import AsyncClient, ASGITransport
import base64
from bexio_receipts.server import app, get_settings


@pytest.mark.asyncio
async def test_csrf_protection(test_settings, tmp_path):
    import json

    app.dependency_overrides[get_settings] = lambda: test_settings

    # Setup test file in review_dir
    review_dir = tmp_path / "review_queue"
    review_dir.mkdir(parents=True)
    test_settings.review_dir = str(review_dir)

    with open(review_dir / "123.json", "w") as f:
        json.dump({"original_file": "test.png"}, f)

    auth = base64.b64encode(b"admin:test_password").decode()
    headers = {"Authorization": f"Basic {auth}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # POST without valid csrf_token
        response = await ac.post(
            "/discard/123", data={"csrf_token": "wrong"}, headers=headers
        )
        assert response.status_code == 403

        # Normal GET will set cookie
        response = await ac.get("/review/123", headers=headers)
        assert response.status_code == 200
        assert "csrf_token" in response.text
