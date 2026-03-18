import asyncio
import email
import logging
from pathlib import Path
from typing import List, Optional

import aioimaplib
import structlog

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient

logger = structlog.get_logger(__name__)

class EmailIngestor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.download_dir = Path(settings.inbox_path) / "email"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.imap_client: Optional[aioimaplib.IMAP4_SSL] = None

    async def connect(self):
        if not self.settings.imap_server:
            raise ValueError("IMAP server not configured.")
            
        self.imap_client = aioimaplib.IMAP4_SSL(self.settings.imap_server)
        await self.imap_client.wait_hello_from_server()
        await self.imap_client.login(self.settings.imap_user, self.settings.imap_password)
        await self.imap_client.select(self.settings.imap_folder)

    async def fetch_new_emails(self):
        """Find UNSEEN emails with attachments."""
        # Search for unread messages
        obj = await self.imap_client.search("UNSEEN")
        msg_ids = obj.lines[0].decode().split()
        
        if not msg_ids or (len(msg_ids) == 1 and not msg_ids[0]):
            return []

        logger.info(f"Found {len(msg_ids)} unseen emails.")
        return msg_ids

    async def process_email(self, msg_id: str):
        """Download attachments from an email and process them."""
        obj = await self.imap_client.fetch(msg_id, "RFC822")
        raw_email = obj.lines[1]
        msg = email.message_from_bytes(raw_email)
        
        subject = msg.get("Subject", "No Subject")
        logger.info(f"Processing email: {subject}")

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue

            filename = part.get_filename()
            if filename:
                ext = Path(filename).suffix.lower()
                if ext in [".png", ".jpg", ".jpeg", ".pdf"]:
                    filepath = self.download_dir / filename
                    logger.info(f"Downloading attachment: {filename}")
                    
                    with open(filepath, "wb") as f:
                        f.write(part.get_payload(decode=True))
                    
                    # Process the file
                    await self._process_file(filepath)

    async def _process_file(self, filepath: Path):
        bexio = BexioClient(
            token=self.settings.bexio_api_token, 
            base_url=self.settings.bexio_base_url
        )
        try:
            await bexio.cache_lookups()
            result = await process_receipt(str(filepath), self.settings, bexio)
            logger.info(f"Email processing finished for {filepath}: {result.get('status')}")
        except Exception as e:
            logger.error(f"Error processing email attachment {filepath}: {e}")
        finally:
            await bexio.close()

    async def run_once(self):
        try:
            await self.connect()
            msg_ids = await self.fetch_new_emails()
            for msg_id in msg_ids:
                await self.process_email(msg_id)
            await self.imap_client.logout()
        except Exception as e:
            logger.error(f"IMAP Error: {e}")

async def watch_email(settings: Settings):
    """Periodically check email for new receipts."""
    if not all([settings.imap_server, settings.imap_user, settings.imap_password]):
        logger.error("IMAP settings are incomplete. Please check your .env file.")
        return

    ingestor = EmailIngestor(settings)
    logger.info(f"Starting email watcher (polling every {settings.imap_poll_interval}s)...")
    
    while True:
        await ingestor.run_once()
        await asyncio.sleep(settings.imap_poll_interval)
