import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from bexio_receipts.cli import main
import sys

def test_cli_process_dry_run(tmp_path, test_settings):
    img_file = tmp_path / "receipt.png"
    img_file.write_text("fake image content")
    
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Patch process_file directly since it's called by main for 'process' command
        with patch("bexio_receipts.cli.process_file") as mock_process:
            with patch.object(sys, "argv", ["bexio-receipts", "process", str(img_file), "--dry-run"]):
                main()
                mock_process.assert_called_once()

def test_cli_process_real(tmp_path, test_settings):
    img_file = tmp_path / "receipt.png"
    img_file.write_text("fake image content")
    test_settings.bexio_api_token = "valid_token"
    
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
            with patch("bexio_receipts.cli.BexioClient") as mock_client:
                mock_client_inst = mock_client.return_value.__aenter__.return_value
                mock_client_inst.cache_lookups = AsyncMock()
                with patch("bexio_receipts.cli.process_receipt") as mock_process:
                    mock_process.return_value = {"status": "booked"}
                    
                    with patch.object(sys, "argv", ["bexio-receipts", "process", str(img_file)]):
                        main()
                        mock_process.assert_called_once()

def test_cli_mappings(tmp_path, test_settings):
    mapping_file = tmp_path / "mappings.json"
    db_file = tmp_path / "test.db"
    test_settings.database_path = str(db_file)
    
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Export
        with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
            mock_db.return_value.get_all_merchant_accounts.return_value = {"Coop": 123}
            with patch.object(sys, "argv", ["bexio-receipts", "export-mappings", str(mapping_file)]):
                main()
                assert mapping_file.exists()
                assert json.loads(mapping_file.read_text()) == {"Coop": 123}
        
        # Import
        with patch("bexio_receipts.database.DuplicateDetector") as mock_db:
            with patch.object(sys, "argv", ["bexio-receipts", "import-mappings", str(mapping_file)]):
                main()
                mock_db.return_value.import_merchant_accounts.assert_called_once_with({"Coop": 123})

def test_cli_reprocess(tmp_path, test_settings):
    img_file = tmp_path / "orig.png"
    img_file.write_text("content")
    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps({"original_file": str(img_file)}))
    
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        with patch("bexio_receipts.cli.process_file") as mock_process:
            with patch.object(sys, "argv", ["bexio-receipts", "reprocess", str(review_file), "--dry-run"]):
                main()
                mock_process.assert_called_once()

def test_cli_config_error():
    from pydantic import ValidationError
    with patch("bexio_receipts.cli.Settings", side_effect=ValidationError.from_exception_data("Settings", [])):
        with patch.object(sys, "argv", ["bexio-receipts", "process", "any.png"]):
            with pytest.raises(SystemExit) as e:
                main()
            assert e.value.code == 1

def test_cli_file_not_found(test_settings):
    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        with patch.object(sys, "argv", ["bexio-receipts", "process", "nonexistent.png"]):
            with pytest.raises(SystemExit) as e:
                main()
            assert e.value.code == 1
