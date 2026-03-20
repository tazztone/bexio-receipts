from bexio_receipts.database import DuplicateDetector


def test_db_stats(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DuplicateDetector(db_path)

    db.mark_processed(
        "hash1",
        "path1",
        "id1",
        total_incl_vat=100.5,
        merchant_name="Migros",
        vat_amount=7.5,
        ocr_confidence=0.95
    )
    db.mark_processed(
        "hash2",
        "path2",
        "id2",
        total_incl_vat=50.0,
        merchant_name="Coop",
        vat_amount=2.5,
        ocr_confidence=0.85
    )

    stats = db.get_stats()
    assert stats["total_processed"] == 2
    assert stats["total_booked"] == 150.5
    assert stats["ocr_confidence_avg"] == 0.9

def test_merchant_mappings(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DuplicateDetector(db_path)
    
    db.set_merchant_account("Migros", 100)
    assert db.get_merchant_account("Migros") == 100
    assert db.get_merchant_account("Unknown") is None
    
    mappings = db.get_all_merchant_accounts()
    assert mappings["Migros"] == 100
    
    db.import_merchant_accounts({"Coop": 200})
    assert db.get_merchant_account("Coop") == 200

def test_gdrive_seen(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DuplicateDetector(db_path)
    
    assert not db.is_gdrive_seen("file1")
    db.mark_gdrive_seen("file1")
    assert db.is_gdrive_seen("file1")

def test_duplicate_detection(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DuplicateDetector(db_path)
    
    img = tmp_path / "test.png"
    img.write_text("hello")
    file_hash = db.get_hash(str(img))
    
    assert db.is_duplicate(file_hash) is None
    db.mark_processed(file_hash, str(img), "bexio123")
    assert db.is_duplicate(file_hash) == "bexio123"

def test_processed_receipts_query(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = DuplicateDetector(db_path)
    
    db.mark_processed("h1", "p1.png", "id1", merchant_name="Migros")
    db.mark_processed("h2", "p2.png", "id2", merchant_name="Coop")
    
    results = db.get_processed_receipts(limit=1)
    assert len(results) == 1
    
    results_search = db.get_processed_receipts(search="Migros")
    assert len(results_search) == 1
    assert results_search[0]["merchant"] == "Migros"
    
    count = db.get_total_processed_count(search="Coop")
    assert count == 1
