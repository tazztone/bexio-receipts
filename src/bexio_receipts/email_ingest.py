import asyncio
import email
from pathlib import Path

import aioimaplib
import structlog

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

class EmailIngestor:
    def __init__(self, settings: Settings, bexio: BexioClient):
        self.settings = settings
        self.bexio = bexio
        self.download_dir = Path(settings.inbox_path) / "email"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.imap_client: aioimaplib.IMAP4_SSL | None = None
        self.db = DuplicateDetector(settings.database_path)

    async def connect(self):
        """Authenticate and connect to IMAP server."""
        if not self.settings.imap_server:
            raise ValueError("IMAP server not configured.")
            
        self.imap_client = aioimaplib.IMAP4_SSL(self.settings.imap_server)
        await self.imap_client.wait_hello_from_server()
        await self.imap_client.login(self.settings.imap_user, self.settings.imap_password)
        await self.imap_client.select(self.settings.imap_folder)

    async def fetch_new_emails(self):
        """Find UNSEEN emails with attachments."""
        obj = await self.imap_client.search("UNSEEN")
        msg_ids = obj.lines[0].decode().split()
        
        if not msg_ids or (len(msg_ids) == 1 and not msg_ids[0]):
            return []

        logger.info("Found unseen emails", count=len(msg_ids))
        return msg_ids

    async def process_email(self, msg_id: str):
        """Download attachments from an email and process them."""
        obj = await self.imap_client.fetch(msg_id, "RFC822")
        raw_email = obj.lines[1]
        msg = email.message_from_bytes(raw_email)
        
        subject = msg.get("Subject", "No Subject")
        logger.info("Processing email", subject=subject)

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
                    logger.info("Downloading attachment", filename=filename)
                    
                    with open(filepath, "wb") as f:
                        f.write(part.get_payload(decode=True))
                    
                    # Process the file
                    await self._process_file(filepath)

    async def _process_file(self, filepath: Path):
        """Run the full pipeline on a file."""
        try:
            result = await process_receipt(str(filepath), self.settings, self.bexio, self.db)
            logger.info("Email attachment processing finished", path=str(filepath), status=result.get("status"))
        except Exception as e:
            logger.error("Error processing email attachment", path=str(filepath), error=str(e))

    async def run_once(self):
        """Single check for new emails."""
        try:
            await self.connect()
            msg_ids = await self.fetch_new_emails()
            for msg_id in msg_ids:
                await self.process_email(msg_id)
            await self.imap_client.logout()
        except Exception as e:
            logger.error("IMAP Error", error=str(e))

async def watch_email(settings: Settings):
    """Periodically check email for new receipts."""
    if not all([settings.imap_server, settings.imap_user, settings.imap_password]):
        logger.error("IMAP settings are incomplete.")
        return

    async with BexioClient(
        token=settings.bexio_api_token, 
        base_url=settings.bexio_base_url
    ) as bexio:
        await bexio.cache_lookups()
        
        ingestor = EmailIngestor(settings, bexio)
        logger.info("Starting email watcher", interval=settings.imap_poll_interval)
        
        while True:
            await ingestor.run_once()
            await asyncio.sleep(settings.imap_poll_interval)
