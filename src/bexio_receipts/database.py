import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

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

    def get_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def is_duplicate(self, file_hash: str) -> Optional[str]:
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
