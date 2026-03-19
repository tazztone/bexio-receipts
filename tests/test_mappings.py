import json
from unittest.mock import patch
from bexio_receipts.cli import main
from bexio_receipts.database import DuplicateDetector

def test_merchant_mappings(tmp_path, test_settings):
    db_path = str(tmp_path / "test.db")
    test_settings.database_path = db_path

    db = DuplicateDetector(db_path)
    db.set_merchant_account("Coop", 100)
    db.set_merchant_account("Migros", 200)

    export_file = tmp_path / "mappings.json"

    with patch("sys.argv", ["bexio-receipts", "export-mappings", str(export_file)]):
        with patch("bexio_receipts.cli.settings", test_settings):
            main()

    assert export_file.exists()
    with open(export_file) as f:
        data = json.load(f)

    assert data["Coop"] == 100
    assert data["Migros"] == 200

    # Modify data for import
    data["Aldi"] = 300
    with open(export_file, "w") as f:
        json.dump(data, f)

    with patch("sys.argv", ["bexio-receipts", "import-mappings", str(export_file)]):
        with patch("bexio_receipts.cli.settings", test_settings):
            main()

    assert db.get_merchant_account("Aldi") == 300
