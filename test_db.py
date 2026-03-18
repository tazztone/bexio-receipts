from src.bexio_receipts.database import DuplicateDetector
import os

if os.path.exists("test.db"):
    os.remove("test.db")

db = DuplicateDetector("test.db")
db.mark_processed("hash1", "path1", "id1", total_incl_vat=100.5, merchant_name="Migros", vat_amount=7.5)
db.mark_processed("hash2", "path2", "id2", total_incl_vat=50.0, merchant_name="Coop", vat_amount=2.5)
db.mark_processed("hash3", "path3", "id3", total_incl_vat=150.0, merchant_name="Migros", vat_amount=10.0)

print(db.get_stats())
