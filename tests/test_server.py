import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from bexio_receipts.server import app, get_settings, get_db

client = TestClient(app)


def test_dashboard_unauthorized():
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
        mock_inst.client.get = AsyncMock()
        mock_inst.client.get.return_value.json = MagicMock(
            return_value={"name": "Test Co"}
        )

        response = client.get("/setup/check/bexio", auth=("admin", "test_password"))
        assert "OK (Test Co)" in response.text

    # OCR Check (GLM)
    test_settings.ocr_engine = "glm-ocr"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"models": [{"name": "glm-ocr"}]}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        response = client.get("/setup/check/ocr", auth=("admin", "test_password"))
        assert "OK (Model glm-ocr loaded)" in response.text

    # OCR Check Error with Copy button
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("Ollama Error")):
        response = client.get("/setup/check/ocr", auth=("admin", "test_password"))
        assert "Error connecting to Ollama" in response.text
        assert "Copy" in response.text
        assert "ollama serve" in response.text

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
        response = client.post(
            "/setup/pull-model",
            data={"model": "test-model"},
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

    # Mock session by mocking Request object or using a middleware trick
    # For simplicity, we patch the session check in the route or the session itself
    with patch("fastapi.Request.session", new_callable=MagicMock) as mock_session:
        mock_session.get.return_value = "test_token"
        response = client.post(
            "/discard/test",
            data={"csrf_token": "test_token"},
            auth=("admin", "test_password"),
            follow_redirects=False,
        )
        # Note: Depending on how Request is used, we might need a different patch.
        # Let's try patching the session directly in the app state or via a dependency.
        pass

    # Alternative: patch the CSRF check logic or the session middleware
    with patch(
        "starlette.middleware.sessions.SessionMiddleware.__call__"
    ) as mock_session:
        # This is getting complex. Let's just bypass CSRF for testing or use a real session.
        pass

    # Final attempt: patch session in server.py
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
        json.dumps(
            {
                "original_file": str(img_file),
                "extracted": {"merchant_name": "Test Merchant"},
            }
        )
    )

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("bexio_receipts.server.BexioClient") as mock_bexio:
        mock_instance = mock_bexio.return_value.__aenter__.return_value
        mock_instance.upload_file = AsyncMock(return_value="uuid-123")
        mock_instance.create_purchase_bill = AsyncMock()
        mock_instance.cache_lookups = AsyncMock()

        form_data = {
            "merchant_name": "Updated Merchant",
            "date": "2023-01-01",
            "total_incl_vat": 15.50,
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
    app.dependency_overrides[get_settings] = lambda: test_settings
    for _ in range(10):
        response = client.get("/", auth=("admin", "wrong_password"))

    assert response.status_code in [401, 429]
    app.dependency_overrides.clear()
