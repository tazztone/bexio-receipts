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
    )
    db.mark_processed(
        "hash2",
        "path2",
        "id2",
        total_incl_vat=50.0,
        merchant_name="Coop",
        vat_amount=2.5,
    )
    db.mark_processed(
        "hash3",
        "path3",
        "id3",
        total_incl_vat=150.0,
        merchant_name="Migros",
        vat_amount=10.0,
    )

    stats = db.get_stats()
    assert stats["total_processed"] == 3
    assert stats["total_booked"] == 300.5
    assert stats["total_vat"] == 20.0
    assert len(stats["top_merchants"]) == 2
    assert stats["top_merchants"][0]["name"] == "Migros"
    assert stats["top_merchants"][0]["amount"] == 250.5
