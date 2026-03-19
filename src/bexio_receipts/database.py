import sqlite3
import hashlib
from datetime import datetime

def adapt_datetime(dt: datetime) -> str:
    return dt.isoformat()

def convert_datetime(s: bytes) -> datetime:
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("TIMESTAMP", convert_datetime)

class DuplicateDetector:
    def __init__(self, db_path: str = "processed_receipts.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(
            self.db_path, 
            timeout=10.0, 
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        self._init_db()

    def _init_db(self):
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_receipts (
                file_hash TEXT PRIMARY KEY,
                file_path TEXT,
                processed_at TIMESTAMP,
                bexio_id TEXT,
                total_incl_vat REAL,
                merchant_name TEXT,
                vat_amount REAL
            )
        """)

        # Migration for existing databases
        try:
            self._conn.execute("ALTER TABLE processed_receipts ADD COLUMN total_incl_vat REAL")
            self._conn.execute("ALTER TABLE processed_receipts ADD COLUMN merchant_name TEXT")
            self._conn.execute("ALTER TABLE processed_receipts ADD COLUMN vat_amount REAL")
        except sqlite3.OperationalError:
            pass # Columns already exist

        try:
            self._conn.execute("ALTER TABLE processed_receipts ADD COLUMN ocr_confidence REAL")
        except sqlite3.OperationalError:
            pass

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_accounts (
                merchant_name TEXT PRIMARY KEY,
                booking_account_id INTEGER
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS gdrive_seen_files (
                file_id TEXT PRIMARY KEY,
                seen_at TIMESTAMP
            )
        """)
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()

    def __del__(self):
        self.close()

    def get_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def is_duplicate(self, file_hash: str) -> str | None:
        """Check if hash exists in DB, returns bexio_id if found."""
        cursor = self._conn.execute(
            "SELECT bexio_id FROM processed_receipts WHERE file_hash = ?",
            (file_hash,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def mark_processed(self, file_hash: str, file_path: str, bexio_id: str,
                       total_incl_vat: float | None = None, merchant_name: str | None = None, vat_amount: float | None = None,
                       ocr_confidence: float | None = None):
        """Record a processed receipt."""
        self._conn.execute(
            """INSERT INTO processed_receipts
               (file_hash, file_path, processed_at, bexio_id, total_incl_vat, merchant_name, vat_amount, ocr_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_hash, str(file_path), datetime.now(), bexio_id, total_incl_vat, merchant_name, vat_amount, ocr_confidence)
        )
        self._conn.commit()

    def get_merchant_account(self, merchant_name: str) -> int | None:
        """Get the last used booking account for a merchant."""
        cursor = self._conn.execute(
            "SELECT booking_account_id FROM merchant_accounts WHERE merchant_name = ?",
            (merchant_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_merchant_account(self, merchant_name: str, account_id: int):
        """Save the booking account for a merchant."""
        self._conn.execute(
            "INSERT OR REPLACE INTO merchant_accounts (merchant_name, booking_account_id) VALUES (?, ?)",
            (merchant_name, account_id)
        )
        self._conn.commit()

    def get_all_merchant_accounts(self) -> dict[str, int]:
        """Get all merchant to booking account mappings."""
        cursor = self._conn.execute("SELECT merchant_name, booking_account_id FROM merchant_accounts")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def import_merchant_accounts(self, mappings: dict[str, int]):
        """Import merchant to booking account mappings."""
        self._conn.executemany(
            "INSERT OR REPLACE INTO merchant_accounts (merchant_name, booking_account_id) VALUES (?, ?)",
            mappings.items()
        )
        self._conn.commit()

    def is_gdrive_seen(self, file_id: str) -> bool:
        """Check if a Google Drive file ID has been seen."""
        cursor = self._conn.execute(
            "SELECT 1 FROM gdrive_seen_files WHERE file_id = ?",
            (file_id,)
        )
        return cursor.fetchone() is not None

    def mark_gdrive_seen(self, file_id: str):
        """Mark a Google Drive file ID as seen."""
        self._conn.execute(
            "INSERT OR IGNORE INTO gdrive_seen_files (file_id, seen_at) VALUES (?, ?)",
            (file_id, datetime.now())
        )
        self._conn.commit()

    def get_stats(self) -> dict:
        """Fetch processing statistics."""
        count = self._conn.execute("SELECT COUNT(*) FROM processed_receipts").fetchone()[0]
        sums = self._conn.execute(
            "SELECT SUM(total_incl_vat), SUM(vat_amount), AVG(ocr_confidence) FROM processed_receipts"
        ).fetchone()

        top_merchants_query = """
            SELECT merchant_name, SUM(total_incl_vat) as total
            FROM processed_receipts
            WHERE merchant_name IS NOT NULL
            GROUP BY merchant_name
            ORDER BY total DESC
            LIMIT 5
        """
        top_merchants = [
            {"name": row[0], "amount": round(row[1], 2) if row[1] else 0}
            for row in self._conn.execute(top_merchants_query).fetchall()
        ]

        return {
            "total_processed": count,
            "total_booked": round(sums[0], 2) if sums and sums[0] else 0.0,
            "total_vat": round(sums[1], 2) if sums and sums[1] else 0.0,
            "ocr_confidence_avg": round(sums[2], 4) if sums and sums[2] else 0.0,
            "top_merchants": top_merchants
        }
