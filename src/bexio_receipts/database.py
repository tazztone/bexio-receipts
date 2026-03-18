import sqlite3
import hashlib
from datetime import datetime

class DuplicateDetector:
    def __init__(self, db_path: str = "processed_receipts.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_receipts (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT,
                    processed_at TIMESTAMP,
                    bexio_id TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS merchant_accounts (
                    merchant_name TEXT PRIMARY KEY,
                    booking_account_id INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gdrive_seen_files (
                    file_id TEXT PRIMARY KEY,
                    seen_at TIMESTAMP
                )
            """)

    def get_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def is_duplicate(self, file_hash: str) -> str | None:
        """Check if hash exists in DB, returns bexio_id if found."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT bexio_id FROM processed_receipts WHERE file_hash = ?", 
                (file_hash,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def mark_processed(self, file_hash: str, file_path: str, bexio_id: str):
        """Record a processed receipt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO processed_receipts (file_hash, file_path, processed_at, bexio_id) VALUES (?, ?, ?, ?)",
                (file_hash, str(file_path), datetime.now(), bexio_id)
            )

    def get_merchant_account(self, merchant_name: str) -> int | None:
        """Get the last used booking account for a merchant."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT booking_account_id FROM merchant_accounts WHERE merchant_name = ?", 
                (merchant_name,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def set_merchant_account(self, merchant_name: str, account_id: int):
        """Save the booking account for a merchant."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO merchant_accounts (merchant_name, booking_account_id) VALUES (?, ?)",
                (merchant_name, account_id)
            )

    def is_gdrive_seen(self, file_id: str) -> bool:
        """Check if a Google Drive file ID has been seen."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM gdrive_seen_files WHERE file_id = ?", 
                (file_id,)
            )
            return cursor.fetchone() is not None

    def mark_gdrive_seen(self, file_id: str):
        """Mark a Google Drive file ID as seen."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO gdrive_seen_files (file_id, seen_at) VALUES (?, ?)",
                (file_id, datetime.now())
            )

    def get_stats(self) -> dict:
        """Fetch processing statistics."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM processed_receipts").fetchone()[0]
            # Simple stats for now, can be expanded to sums, counts by merchant etc.
            return {"total_processed": count}
