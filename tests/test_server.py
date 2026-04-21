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
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_inst.__aenter__.return_value.client.get = AsyncMock(
                return_value=mock_response
            )
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
        mock_response_setup = MagicMock()
        mock_response_setup.raise_for_status = MagicMock()
        mock_inst.client.get = AsyncMock(return_value=mock_response_setup)
        mock_inst.client.get.return_value.json = MagicMock(
            return_value={"name": "Test Co"}
        )

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


def test_history(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
        mock_db_inst = MagicMock()
        mock_db.return_value = mock_db_inst
        mock_db_inst.get_processed_receipts.return_value = [{"id": 1}]
        mock_db_inst.get_total_processed_count.return_value = 1

        response = client.get("/history?page=1", auth=("admin", "test_password"))
        assert response.status_code == 200
    app.dependency_overrides.clear()


def test_bulk_action_process(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    test_settings.bexio_push_enabled = True

    review_file1 = review_dir / "test1.json"
    review_file1.write_text(
        json.dumps({
            "original_file": "test1.png",
            "extracted": {"merchant_name": "Test1", "total_incl_vat": 10.0},
        })
    )

    with (
        patch(
            "bexio_receipts.server.Request.session",
            property(lambda x: {"csrf_token": "test_token"}),
        ),
        patch("bexio_receipts.server.BexioClient") as mock_bexio,
    ):
        mock_instance = mock_bexio.return_value.__aenter__.return_value
        mock_instance.upload_file = AsyncMock(return_value="uuid-123")
        mock_instance.create_expense = AsyncMock()
        mock_instance.cache_lookups = AsyncMock()

        response = client.post(
            "/bulk-action",
            data={"csrf_token": "test_token", "ids": ["test1"], "action": "process"},
            auth=("admin", "test_password"),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert not review_file1.exists()

    app.dependency_overrides.clear()


def test_push_missing_account(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    img_file = tmp_path / "test.png"
    img_file.write_text("fake image")

    review_file = review_dir / "test_id2.json"
    review_file.write_text(
        json.dumps({
            "original_file": str(img_file),
            "extracted": {"merchant_name": "Test Merchant"},
        })
    )

    with patch(
        "bexio_receipts.server.Request.session",
        property(lambda x: {"csrf_token": "test_token"}),
    ):
        response = client.post(
            "/push/test_id2",
            data={
                "merchant_name": "Updated Merchant",
                "date": "2023-01-01",
                "total_incl_vat": "15.50",
                "booking_account_ids": ["100", "200"],  # count mismatch
                "bexio_action": "purchase_bill",
                "csrf_token": "test_token",
            },
            auth=("admin", "test_password"),
            follow_redirects=False,
        )
        assert response.status_code == 422
    app.dependency_overrides.clear()


def test_metrics(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    with patch(
        "bexio_receipts.database.DuplicateDetector.get_stats",
        return_value={"total_processed": 10, "ocr_confidence_avg": 0.95},
    ):
        response = client.get("/metrics", auth=("admin", "test_password"))
        assert response.status_code == 200
        assert b"receipts_processed_total 10.0" in response.content
    app.dependency_overrides.clear()


def test_thumbnail_success(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    test_settings.inbox_path = str(tmp_path / "inbox")

    from PIL import Image

    img_path = review_dir / "test_thumb.jpg"
    img = Image.new("RGB", (10, 10))
    img.save(img_path)

    review_file = review_dir / "test_id.json"
    review_file.write_text(json.dumps({"original_file": str(img_path)}))

    response = client.get("/thumbnail/test_id", auth=("admin", "test_password"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    app.dependency_overrides.clear()


def test_thumbnail_404_no_image(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)

    review_file = review_dir / "test_id.json"
    review_file.write_text(json.dumps({"original_file": "/nonexistent/path/img.jpg"}))

    response = client.get("/thumbnail/test_id", auth=("admin", "test_password"))
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_thumbnail_403_outside_root(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    test_settings.inbox_path = str(tmp_path / "inbox")

    # Path outside allowed roots
    img_path = tmp_path / "other" / "test_thumb.jpg"
    img_path.parent.mkdir()
    img_path.write_text("fake image")

    review_file = review_dir / "test_id.json"
    review_file.write_text(json.dumps({"original_file": str(img_path)}))

    response = client.get("/thumbnail/test_id", auth=("admin", "test_password"))
    assert response.status_code == 403
    app.dependency_overrides.clear()


def test_review_form_success(test_settings, tmp_path):
    app.dependency_overrides[get_settings] = lambda: test_settings
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    test_settings.review_dir = str(review_dir)
    test_settings.bexio_allowed_soll_accounts = [4200]
    test_settings.bexio_haben_account_bank = 1020
    test_settings.bexio_haben_account_cash = 1000

    review_file = review_dir / "test_id.json"
    review_file.write_text(
        json.dumps({
            "extracted": {
                "merchant_name": "Test",
                "total_incl_vat": 10.0,
                "currency": "CHF",
                "vat_breakdown": [
                    {"rate": 8.1, "vat_amount": 0.81, "base_amount": 10.0}
                ],
            },
            "extraction_trace": {
                "step3_assignments": [
                    {
                        "vat_rate": 8.1,
                        "account_id": "1",
                        "confidence": "high",
                        "reasoning": "test",
                    }
                ]
            },
        })
    )

    with patch("bexio_receipts.server.BexioClient") as mock_bexio:
        mock_instance = mock_bexio.return_value.__aenter__.return_value
        mock_instance.get_accounts = AsyncMock(
            return_value=[
                {"id": 1, "account_no": "4200", "name": "Material"},
                {"id": 2, "account_no": "1020", "name": "Bank"},
                {"id": 3, "account_no": "1000", "name": "Cash"},
            ]
        )

        response = client.get("/review/test_id", auth=("admin", "test_password"))
        assert response.status_code == 200
        assert "Test" in response.text
    app.dependency_overrides.clear()
