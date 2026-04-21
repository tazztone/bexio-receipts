import json
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from bexio_receipts.cli import app

runner = CliRunner()


def test_cli_process_dry_run(tmp_path, test_settings):
    img_file = tmp_path / "receipt.png"
    img_file.write_text("fake image content")

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Patch the underlying functions via the processor
        with patch("bexio_receipts.pipeline.get_processor") as mock_get:
            mock_processor = AsyncMock()
            mock_get.return_value = mock_processor
            from bexio_receipts.document_processor import ProcessingResult
            from bexio_receipts.extraction import ExtractionTrace

            mock_processor.process.return_value = ProcessingResult(
                raw_text="raw text",
                merchant_name="Test",
                total_incl_vat=10.0,
                confidence=0.9,
                trace=ExtractionTrace(),
            )

            result = runner.invoke(app, ["process", str(img_file), "--dry-run"])
            assert result.exit_code == 0
            mock_processor.process.assert_called_once()


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
            mock_db.return_value.import_merchant_accounts.assert_called_once_with({
                "Coop": 123
            })


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


def test_cli_init_quickstart(tmp_path, test_settings):
    # Mocking fixtures/sample_receipt.png
    fixtures_dir = tmp_path / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    sample_img = fixtures_dir / "sample_receipt.png"
    sample_img.write_text("fake image")

    with patch(
        "bexio_receipts.cli.Path",
        side_effect=lambda x: tmp_path / x,
    ):
        # We need to be careful with Path patching
        pass

    # Simplified patch for init
    with patch("bexio_receipts.cli.Path") as mock_path:
        # Mock .env path
        mock_env = MagicMock()
        mock_env.exists.return_value = False

        # Mock fixtures path
        mock_fixtures = MagicMock()
        mock_fixtures.exists.return_value = True

        def path_side_effect(path_str):
            if str(path_str) == ".env":
                return mock_env
            if "fixtures" in str(path_str):
                return mock_fixtures
            return MagicMock()

        mock_path.side_effect = path_side_effect

        with patch("shutil.copy"):
            with patch("bexio_receipts.pipeline.get_processor") as mock_get:
                mock_processor = AsyncMock()
                mock_get.return_value = mock_processor
                from bexio_receipts.document_processor import ProcessingResult
                from bexio_receipts.extraction import ExtractionTrace

                mock_processor.process.return_value = ProcessingResult(
                    raw_text="raw",
                    merchant_name="Test",
                    total_incl_vat=10.0,
                    confidence=0.9,
                    trace=ExtractionTrace(),
                )

                with patch("bexio_receipts.cli.Settings", return_value=test_settings):
                    result = runner.invoke(app, ["init", "--quickstart"])
                    assert result.exit_code == 0
                    assert "Quickstart complete" in result.stdout


def test_cli_file_not_found(test_settings):
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        result = runner.invoke(app, ["process", "nonexistent.png"])
        assert result.exit_code == 2
