import asyncio
import io
import os
import stat
from pathlib import Path

import structlog
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

# Full 'drive' scope is required to move files (update parents)
SCOPES = ["https://www.googleapis.com/auth/drive"]

class GoogleDriveIngestor:
    def __init__(self, settings: Settings, bexio: BexioClient):
        self.settings = settings
        self.bexio = bexio
        self.download_dir = Path(settings.inbox_path) / "gdrive"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.service = None
        self.db = DuplicateDetector(settings.database_path)

    async def connect(self):
        """Authenticate and build the Drive service (non-interactive)."""
        if not self.settings.gdrive_credentials_file:
            raise ValueError("Google Drive credentials file not configured.")

        creds = None
        creds_path = Path(self.settings.gdrive_credentials_file)
        
        # Check permissions
        if creds_path.exists():
            st = os.stat(creds_path)
            if bool(st.st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
                logger.warning("Google Drive credentials file has insecure permissions (too open). Consider running `chmod 600` on it.", path=str(creds_path))

        # 1. Try Service Account
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=SCOPES
            )
            logger.info("Authenticated with Google Service Account", credentials=str(creds_path))
        except Exception:
            # 2. Try existing OAuth2 token (non-interactive)
            token_path = Path(self.settings.gdrive_token_path)
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    await asyncio.to_thread(creds.refresh, Request())
                    with open(token_path, "w") as token:
                        token.write(creds.to_json())
                    logger.info("Refreshed Google OAuth2 token")
                else:
                    raise RuntimeError(
                        f"Google OAuth2 token missing or invalid at {token_path}. "
                        "Please run 'bexio-receipts gdrive-auth' first."
                    )
            else:
                logger.info("Authenticated with Google OAuth2 token", path=str(token_path))

        self.service = build("drive", "v3", credentials=creds)

    async def list_new_files(self):
        """Find files in the specified folder (async-wrapped)."""
        if not self.settings.gdrive_folder_id:
            logger.error("Google Drive folder ID not configured.")
            return []

        query = f"'{self.settings.gdrive_folder_id}' in parents and trashed = false"
        
        # Execute blocking call in thread
        if self.service is None:
            return []
            
        results = await asyncio.to_thread(
            self.service.files().list(
                q=query, 
                fields="files(id, name, mimeType, md5Checksum, createdTime)",
                orderBy="createdTime"
            ).execute
        )
        
        files = results.get("files", [])
        valid_files = []
        for f in files:
            name = f.get("name", "").lower()
            if name.endswith((".png", ".jpg", ".jpeg", ".pdf")):
                valid_files.append(f)
        
        return valid_files

    async def download_file(self, file_id: str, file_name: str) -> Path:
        """Download a file from Drive (async-wrapped)."""
        if self.service is None:
            raise RuntimeError("Drive service not connected")
        request = self.service.files().get_media(fileId=file_id)
        file_path = self.download_dir / file_name
        
        # Ensure filename is unique
        counter = 1
        original_name = file_path.name
        while file_path.exists():
            stem = Path(original_name).stem
            suffix = Path(original_name).suffix
            file_path = self.download_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        with io.FileIO(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                # next_chunk() is blocking
                _, done = await asyncio.to_thread(downloader.next_chunk)
            
        return file_path

    async def archive_file(self, file_id: str):
        """Move the file to the processed folder (async-wrapped)."""
        if not self.settings.gdrive_processed_folder_id:
            return

        # Retrieve parents
        if self.service is None:
            return
            
        file = await asyncio.to_thread(
            self.service.files().get(fileId=file_id, fields="parents").execute
        )
        previous_parents = ",".join(file.get("parents", []))
        
        # Move file
        if self.service is None:
            return

        await asyncio.to_thread(
            self.service.files().update(
                fileId=file_id,
                addParents=self.settings.gdrive_processed_folder_id,
                removeParents=previous_parents,
                fields="id, parents"
            ).execute
        )
        logger.info("Archived Google Drive file", file_id=file_id, folder_id=self.settings.gdrive_processed_folder_id)

    async def run_once(self):
        """Single polling cycle."""
        try:
            if not self.service:
                await self.connect()

            files = await self.list_new_files()
            if not files:
                return

            potential_files = [f for f in files if not self.db.is_gdrive_seen(f.get("id"))]
            if not potential_files:
                return

            logger.info("Processing new files from Google Drive", count=len(potential_files))
            
            for f in potential_files:
                file_id = f.get("id")
                file_name = f.get("name")
                
                # Download to check hash
                file_path = await self.download_file(file_id, file_name)
                
                try:
                    result = await process_receipt(str(file_path), self.settings, self.bexio, self.db)
                    status = result.get("status")
                    logger.info("Google Drive processing finished", file=file_name, status=status)
                    
                    if status in ["booked", "duplicate"]:
                        await self.archive_file(file_id)
                        self.db.mark_gdrive_seen(file_id)
                        # Delete local temp file if successfully booked or already processed
                        if file_path.exists():
                            file_path.unlink()
                    else:
                        # For "review" or "review_failed", we keep the local file
                        # so it's available for the dashboard/manual inspection.
                        self.db.mark_gdrive_seen(file_id)

                except Exception as e:
                    logger.error("Error processing Google Drive file", file=file_name, error=str(e))
        except Exception as e:
            logger.error("Google Drive polling error", error=str(e))

async def watch_gdrive(settings: Settings, folder_id: str | None = None):
    """Periodically check Google Drive for new receipts."""
    if folder_id:
        settings.gdrive_folder_id = folder_id

    if not settings.gdrive_credentials_file:
        logger.error("Google Drive credentials file is not set.")
        return

    async with BexioClient(
        token=settings.bexio_api_token, 
        base_url=settings.bexio_base_url,
        default_vat_rate=settings.default_vat_rate
    ) as bexio:
        await bexio.cache_lookups()
        ingestor = GoogleDriveIngestor(settings, bexio)
        
        # Initial connect check
        try:
            await ingestor.connect()
        except Exception as e:
            logger.error("Initial Google Drive connection failed", error=str(e))
            return

        logger.info("Starting Google Drive watcher", interval=settings.gdrive_poll_interval)
        
        while True:
            await ingestor.run_once()
            await asyncio.sleep(settings.gdrive_poll_interval)

def run_gdrive_auth(settings: Settings):
    """Interactive OAuth2 flow for Google Drive."""
    if not settings.gdrive_credentials_file:
        print("Error: GDRIVE_CREDENTIALS_FILE not set in settings.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        settings.gdrive_credentials_file, SCOPES
    )
    creds = flow.run_local_server(port=0)
    
    with open(settings.gdrive_token_path, "w") as token:
        token.write(creds.to_json())
    
    print(f"Successfully saved OAuth2 token to {settings.gdrive_token_path}")
    print("\nYou can now run: uv run bexio-receipts watch-gdrive")
