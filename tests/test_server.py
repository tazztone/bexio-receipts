import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from bexio_receipts.server import app, get_db, get_settings

client = TestClient(app)


def test_dashboard_unauthorized():
    # Clear any override left by a previous test so auth is actually enforced.
    app.dependency_overrides.clear()
    response = client.get("/")
    assert response.status_code == 401


def test_dashboard_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/", auth=("admin", "test_password"))
    assert response.status_code == 200
    app.dependency_overrides.clear()


def test_stats_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/stats", auth=("admin", "test_password"))
    assert response.status_code == 200
    app.dependency_overrides.clear()


def test_healthz_ok(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    with patch("sqlite3.connect") as mock_sql:
        mock_sql.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
            1,
        )
        with patch("bexio_receipts.server.BexioClient") as mock_bexio:
            mock_inst = mock_bexio.return_value
            mock_inst.__aenter__.return_value.client.get = AsyncMock()
            mock_inst.__aenter__.return_value.client.get.return_value.raise_for_status = MagicMock()
            response = client.get("/healthz")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    app.dependency_overrides.clear()


def test_healthz_error(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    with patch("sqlite3.connect", side_effect=Exception("DB Error")):
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "error"
        assert "DB Error" in response.json()["db"]
    app.dependency_overrides.clear()


def test_setup_wizard(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/setup", auth=("admin", "test_password"))
    assert response.status_code == 200
    app.dependency_overrides.clear()


def test_setup_checks(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Bexio Check
    with patch("bexio_receipts.server.BexioClient") as mock_bexio:
        mock_inst = MagicMock()
        mock_bexio.return_value.__aenter__.return_value = mock_inst
        mock_bexio_resp = MagicMock()
        mock_bexio_resp.json.return_value = {"name": "Test Co"}
        mock_bexio_resp.raise_for_status = MagicMock()
        mock_inst.client.get = AsyncMock(return_value=mock_bexio_resp)

        response = client.get("/setup/check/bexio", auth=("admin", "test_password"))
        assert "OK (Test Co)" in response.text

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        response = client.get("/setup/check/ocr", auth=("admin", "test_password"))
        assert "OK (vLLM GLM-OCR service reachable)" in response.text

    # OCR Check Error
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=Exception("Connection refused"),
    ):
        response = client.get("/setup/check/ocr", auth=("admin", "test_password"))
        assert "Error connecting to GLM-OCR" in response.text

    # LLM Check (Ollama)
    test_settings.llm_provider = "ollama"
    test_settings.llm_model = "qwen3.5"
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        mock_resp.json.return_value = {"models": [{"name": "qwen3.5"}]}
        response = client.get("/setup/check/llm", auth=("admin", "test_password"))
        assert "OK (Model qwen3.5 loaded)" in response.text

    # System Check
    with patch("shutil.which", return_value="/usr/bin/pdftoppm"):
        response = client.get("/setup/check/system", auth=("admin", "test_password"))
        assert "OK (/usr/bin/pdftoppm)" in response.text

    # System Check Error with Copy button
    with patch("shutil.which", return_value=None):
        response = client.get("/setup/check/system", auth=("admin", "test_password"))
        assert "Error: Poppler not found" in response.text
        assert "Copy" in response.text
        assert "sudo apt install poppler-utils" in response.text

    # DB Check
    with patch("sqlite3.connect"):
        response = client.get("/setup/check/db", auth=("admin", "test_password"))
        assert "OK" in response.text

    app.dependency_overrides.clear()


def test_bulk_discard_review(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_file1 = review_dir / "test1.json"
    review_file1.write_text("{}")
    review_file2 = review_dir / "test2.json"
    review_file2.write_text("{}")

    with patch(
        "bexio_receipts.server.Request.session",
        property(lambda x: {"csrf_token": "test_token"}),
    ):
        response = client.post(
            "/bulk-discard",
            data={"csrf_token": "test_token", "ids": ["test1", "test2"]},
            auth=("admin", "test_password"),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert not review_file1.exists()
        assert not review_file2.exists()

    app.dependency_overrides.clear()


def test_run_all_checks(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/setup/run-all", auth=("admin", "test_password"))
    assert response.status_code == 200
    assert "HX-Trigger" in response.headers
    app.dependency_overrides.clear()


def test_pull_model_success(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ):
        with patch(
            "bexio_receipts.server.Request.session",
            property(lambda x: {"csrf_token": "test_token"}),
        ):
            response = client.post(
                "/setup/pull-model",
                data={"model": "test-model", "csrf_token": "test_token"},
                auth=("admin", "test_password"),
            )
            assert "Successfully pulled test-model" in response.text
    app.dependency_overrides.clear()


def test_review_404(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/review/nonexistent", auth=("admin", "test_password"))
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_image_404(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/image/nonexistent", auth=("admin", "test_password"))
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_discard_review(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_file = review_dir / "test.json"
    review_file.write_text("{}")

    with patch(
        "bexio_receipts.server.Request.session",
        property(lambda x: {"csrf_token": "test_token"}),
    ):
        response = client.post(
            "/discard/test",
            data={"csrf_token": "test_token"},
            auth=("admin", "test_password"),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert not review_file.exists()

    app.dependency_overrides.clear()


def test_push_to_bexio_success(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    img_file = tmp_path / "test.png"
    img_file.write_text("fake image")

    review_file = review_dir / "test_id.json"
    review_file.write_text(
        json.dumps({
            "original_file": str(img_file),
            "extracted": {"merchant_name": "Test Merchant"},
        })
    )

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("bexio_receipts.server.BexioClient") as mock_bexio:
        mock_instance = mock_bexio.return_value.__aenter__.return_value
        mock_instance.upload_file = AsyncMock(return_value="uuid-123")
        mock_instance.create_purchase_bill = AsyncMock(return_value={"id": 42})
        mock_instance.cache_lookups = AsyncMock()

        # booking_account_ids is list[int]; send a single element via repeated key.
        # vat_breakdown is None for this receipt so expected_count == 1.
        form_data = {
            "merchant_name": "Updated Merchant",
            "date": "2023-01-01",
            "total_incl_vat": "15.50",
            "booking_account_ids": ["100"],
            "bexio_action": "purchase_bill",
            "csrf_token": "test_token",
        }

        with patch(
            "bexio_receipts.server.Request.session",
            property(lambda x: {"csrf_token": "test_token"}),
        ):
            response = client.post(
                "/push/test_id",
                data=form_data,
                auth=("admin", "test_password"),
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert not review_file.exists()
            mock_instance.upload_file.assert_called_once()
            mock_instance.create_purchase_bill.assert_called_once()
            mock_db.mark_processed.assert_called_once()

    app.dependency_overrides.clear()


def test_auth_rate_limit(test_settings):
    # Reset the in-process limiter store so previous test runs don't pre-exhaust the quota.
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        app.state.limiter.reset()
    except Exception:
        pass

    for _ in range(10):
        response = client.get("/", auth=("admin", "wrong_password"))

    assert response.status_code in [401, 429]
    app.dependency_overrides.clear()


def test_favicon():
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"


def test_corrupt_review_json(tmp_path, test_settings):
    test_settings.review_dir = str(tmp_path)
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Create a corrupted JSON file
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{invalid: json}")

    response = client.get("/review/corrupt", auth=("admin", "test_password"))
    assert response.status_code == 422
    assert "Review file corrupt" in response.text

    # Test dashboard skipping corrupted file
    # Create one valid and one corrupted
    (tmp_path / "valid.json").write_text(
        json.dumps({
            "original_file": "test.png",
            "extracted": {"merchant_name": "Test"},
        })
    )

    response = client.get("/", auth=("admin", "test_password"))
    assert response.status_code == 200
    assert "Test" in response.text
    # Corrupt file should be skipped without crashing the whole page
    assert "corrupt" not in response.text

    app.dependency_overrides.clear()

def test_thumbnail_success(test_settings, tmp_path):
    # Mock review and image file
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    test_settings.inbox_path = str(tmp_path)

    img_path = review_dir / "test_receipt.jpg"

    from PIL import Image
    # Create fake image
    img = Image.new("RGB", (400, 400), color="white")
    img.save(img_path)

    review_id = "test_review_id"
    import json
    with open(review_dir / f"{review_id}.json", "w") as f:
        json.dump({"original_file": str(img_path)}, f)

    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get(f"/thumbnail/{review_id}", auth=("admin", "test_password"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"

def test_thumbnail_invalid_id(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/thumbnail/invalid..id!", auth=("admin", "test_password"))
    assert response.status_code == 400
    assert "Invalid review ID" in response.text

def test_thumbnail_missing_file(test_settings, tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_id = "test_missing_file"
    import json
    with open(review_dir / f"{review_id}.json", "w") as f:
        json.dump({"original_file": "does_not_exist.jpg"}, f)

    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get(f"/thumbnail/{review_id}", auth=("admin", "test_password"))
    assert response.status_code == 404
    assert "Image file not found" in response.text

def test_thumbnail_access_denied(test_settings, tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_id = "test_access_denied"
    import json
    with open(review_dir / f"{review_id}.json", "w") as f:
        json.dump({"original_file": "/etc/passwd"}, f)

    # /etc/passwd exists but not in allowed roots
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get(f"/thumbnail/{review_id}", auth=("admin", "test_password"))
    assert response.status_code == 403
    assert "Access denied" in response.text

@patch("bexio_receipts.server.BexioClient")
def test_history_and_stats_endpoints(mock_bexio, test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings

    response = client.get("/history", auth=("admin", "test_password"))
    assert response.status_code == 200

    response = client.get("/stats", auth=("admin", "test_password"))
    assert response.status_code == 200

def test_setup_check_llm_missing_model(test_settings):
    test_settings.llm_provider = "ollama"
    test_settings.llm_model = "missing_model"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"models": [{"name": "qwen3.5"}]}
    mock_resp.raise_for_status = MagicMock()

    app.dependency_overrides[get_settings] = lambda: test_settings
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        response = client.get("/setup/check/llm", auth=("admin", "test_password"))
        assert "Warning: Model missing_model not found" in response.text

def test_setup_check_llm_openai_key(test_settings):
    test_settings.llm_provider = "openai"
    test_settings.openai_api_key = "test_key"

    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/setup/check/llm", auth=("admin", "test_password"))
    assert "OK (Openai API Key set)" in response.text
@patch("bexio_receipts.server.BexioClient")
def test_review_endpoint_fallback_assignments(mock_bexio, test_settings, tmp_path):
    # Test lines 596-615: Step 3 assignment fallback
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_id = "test_review_id"
    import json
    # trace should have step3_assignments, extracted should have vat_breakdown
    review_data = {
        "original_file": "fake.jpg",
        "extracted": {
            "merchant_name": "Test Store",
            "vat_breakdown": [{"rate": 8.1, "base_amount": 100, "vat_amount": 8.1, "total_incl_vat": 108.1}]
        },
        "extraction_trace": {
            "step3_assignments": [{"vat_rate": 8.1, "account_id": "4201"}]
        }
    }
    with open(review_dir / f"{review_id}.json", "w") as f:
        json.dump(review_data, f)

    app.dependency_overrides[get_settings] = lambda: test_settings

    # We patch db to return None for merchant account so it triggers the fallback loop
    with patch("bexio_receipts.server.get_db") as mock_db:
        mock_db_inst = MagicMock()
        mock_db_inst.get_merchant_vat_account.return_value = None
        mock_db.return_value = mock_db_inst

        # We need to mock get_accounts since it calls the API
        async def mock_get_accounts():
            return [{"id": 4201, "account_no": "4201", "name": "Test Account"}]
        mock_bexio.return_value.__aenter__.return_value.get_accounts = mock_get_accounts

        response = client.get(f"/review/{review_id}", auth=("admin", "test_password"))
        assert response.status_code == 200
        # The HTML should contain the account ID selected from the fallback
        assert "4201" in response.text
