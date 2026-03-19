import json
from unittest.mock import patch, AsyncMock
from bexio_receipts.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_process_dry_run(tmp_path, test_settings):
    img_file = tmp_path / "receipt.png"
    img_file.write_text("fake image content")

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Patch the underlying functions instead of process_file
        with patch(
            "bexio_receipts.ocr.async_run_ocr", new_callable=AsyncMock
        ) as mock_ocr:
            mock_ocr.return_value = ("raw text", 0.9, {})
            with patch(
                "bexio_receipts.extraction.extract_receipt", new_callable=AsyncMock
            ) as mock_extract:
                from bexio_receipts.models import Receipt

                mock_extract.return_value = Receipt(
                    merchant_name="Test", total_incl_vat=10.0
                )

                result = runner.invoke(app, ["process", str(img_file), "--dry-run"])
                assert result.exit_code == 0
                mock_ocr.assert_called_once()
                mock_extract.assert_called_once()


def test_cli_process_real(tmp_path, test_settings):
    img_file = tmp_path / "receipt.png"
    img_file.write_text("fake image content")
    test_settings.bexio_api_token = "valid_token"

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        with patch("bexio_receipts.database.DuplicateDetector"):
            with patch("bexio_receipts.cli.BexioClient") as mock_client:
                mock_client_inst = mock_client.return_value.__aenter__.return_value
                mock_client_inst.cache_lookups = AsyncMock()
                with patch(
                    "bexio_receipts.cli.process_receipt", new_callable=AsyncMock
                ) as mock_process:
                    mock_process.return_value = {"status": "booked"}

                    result = runner.invoke(app, ["process", str(img_file)])
                    assert result.exit_code == 0
                    mock_process.assert_called_once()


def test_cli_mappings(tmp_path, test_settings):
    mapping_file = tmp_path / "mappings.json"
    db_file = tmp_path / "test.db"
    test_settings.database_path = str(db_file)

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Export
        with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
            mock_db.return_value.get_all_merchant_accounts.return_value = {"Coop": 123}
            result = runner.invoke(app, ["mapping", "export", str(mapping_file)])
            assert result.exit_code == 0
            assert mapping_file.exists()
            assert json.loads(mapping_file.read_text()) == {"Coop": 123}

        # Import
        with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
            result = runner.invoke(app, ["mapping", "import", str(mapping_file)])
            assert result.exit_code == 0
            mock_db.return_value.import_merchant_accounts.assert_called_once_with(
                {"Coop": 123}
            )


def test_cli_reprocess(tmp_path, test_settings):
    img_file = tmp_path / "orig.png"
    img_file.write_text("content")
    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps({"original_file": str(img_file)}))

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        with patch("bexio_receipts.database.DuplicateDetector"):
            with patch("bexio_receipts.cli.BexioClient") as mock_client:
                mock_client_inst = mock_client.return_value.__aenter__.return_value
                mock_client_inst.cache_lookups = AsyncMock()
                # Mock get_profile to avoid 404 in tests
                mock_client_inst.get_profile = AsyncMock(
                    return_value={"id": 1, "name": "Test User"}
                )
                with patch(
                    "bexio_receipts.cli.process_receipt", new_callable=AsyncMock
                ) as mock_process:
                    mock_process.return_value = {"status": "booked"}
                    result = runner.invoke(app, ["reprocess", str(review_file)])
                    assert result.exit_code == 0
                    mock_process.assert_called_once()


def test_cli_config_error():
    from pydantic import ValidationError

    with patch(
        "bexio_receipts.cli.Settings",
        side_effect=ValidationError.from_exception_data("Settings", []),
    ):
        # Run a command that triggers get_settings (all of them except help)
        result = runner.invoke(app, ["serve"])
        assert result.exit_code == 1


def test_cli_file_not_found(test_settings):
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        result = runner.invoke(app, ["process", "nonexistent.png"])
        assert result.exit_code == 2
