import json
from unittest.mock import patch

from typer.testing import CliRunner

from bexio_receipts.cli import app
from bexio_receipts.database import DuplicateDetector

runner = CliRunner()


def test_merchant_mappings(tmp_path, test_settings):
    db_path = str(tmp_path / "test.db")
    test_settings.database_path = db_path

    db = DuplicateDetector(db_path)
    db.set_merchant_account("Coop", 100)
    db.set_merchant_account("Migros", 200)

    export_file = tmp_path / "mappings.json"

    with patch("bexio_receipts.cli.Settings", return_value=test_settings):
        # Export
        result = runner.invoke(app, ["mapping", "export", str(export_file)])
        assert result.exit_code == 0

        assert export_file.exists()
        with open(export_file) as f:
            data = json.load(f)

        assert data["COOP"] == 100
        assert data["MIGROS"] == 200

        # Modify data for import
        data["Aldi"] = 300
        with open(export_file, "w") as f:
            json.dump(data, f)

        # Import
        result = runner.invoke(app, ["mapping", "import", str(export_file)])
        assert result.exit_code == 0
        assert db.get_merchant_account("Aldi") == 300
