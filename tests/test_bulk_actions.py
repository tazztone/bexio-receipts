import pytest
import json
import base64
from httpx import AsyncClient, ASGITransport
from bexio_receipts.server import app, get_settings, get_db
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

@pytest.mark.asyncio
async def test_bulk_discard(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    
    # Create two review files
    (review_dir / "1.json").write_text(json.dumps({"original_file": "1.png"}))
    (review_dir / "2.json").write_text(json.dumps({"original_file": "2.png"}))

    auth = base64.b64encode(b"admin:test_password").decode()
    headers = {"Authorization": f"Basic {auth}"}
    
    # Mock CSRF in session
    with patch("bexio_receipts.server.Request.session", property(lambda x: {"csrf_token": "test_token"})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/bulk-action", 
                data={"ids": ["1", "2"], "action": "discard", "csrf_token": "test_token"},
                headers=headers
            )
            assert response.status_code == 303
            assert not (review_dir / "1.json").exists()
            assert not (review_dir / "2.json").exists()

@pytest.mark.asyncio
async def test_bulk_process(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    
    img_path = tmp_path / "test.png"
    img_path.write_text("content")
    
    # Create a review file
    (review_dir / "1.json").write_text(json.dumps({
        "original_file": str(img_path),
        "extracted": {"merchant_name": "Test", "total_incl_vat": 10.0}
    }))

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    
    auth = base64.b64encode(b"admin:test_password").decode()
    headers = {"Authorization": f"Basic {auth}"}

    with patch("bexio_receipts.server.BexioClient") as mock_bexio:
        mock_instance = mock_bexio.return_value.__aenter__.return_value
        mock_instance.upload_file = AsyncMock(return_value="uuid-123")
        mock_instance.create_purchase_bill = AsyncMock()
        mock_instance.cache_lookups = AsyncMock()

        with patch("bexio_receipts.server.Request.session", property(lambda x: {"csrf_token": "test_token"})):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post(
                    "/bulk-action", 
                    data={"ids": ["1"], "action": "process", "csrf_token": "test_token"},
                    headers=headers
                )
                assert response.status_code == 303
                assert not (review_dir / "1.json").exists()
                mock_instance.create_purchase_bill.assert_called_once()

    app.dependency_overrides.clear()
