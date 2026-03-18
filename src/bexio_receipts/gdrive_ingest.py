import asyncio
import io
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

# If modifying these scopes, delete the file token.json.
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
        """Authenticate and build the Drive service."""
        if not self.settings.gdrive_credentials_file:
            raise ValueError("Google Drive credentials file not configured.")

        creds = None
        creds_path = Path(self.settings.gdrive_credentials_file)
        
        # Check if it's a service account
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=SCOPES
            )
            logger.info("Authenticated with Google Service Account", credentials=str(creds_path))
        except Exception:
            # Fallback to OAuth2 flow for personal accounts
            token_path = Path("token.json")
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(creds_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            logger.info("Authenticated with Google OAuth2", credentials=str(creds_path))

        self.service = build("drive", "v3", credentials=creds)

    async def list_new_files(self):
        """Find files in the specified folder."""
        if not self.settings.gdrive_folder_id:
            logger.error("Google Drive folder ID not configured.")
            return []

        query = f"'{self.settings.gdrive_folder_id}' in parents and trashed = false"
        results = self.service.files().list(
            q=query, 
            fields="files(id, name, mimeType, md5Checksum, createdTime)",
            orderBy="createdTime"
        ).execute()
        
        files = results.get("files", [])
        # Filter by extension/mimetype
        valid_files = []
        for f in files:
            name = f.get("name", "").lower()
            if name.endswith((".png", ".jpg", ".jpeg", ".pdf")):
                valid_files.append(f)
        
        return valid_files

    async def download_file(self, file_id: str, file_name: str) -> Path:
        """Download a file from Drive to the local download directory."""
        request = self.service.files().get_media(fileId=file_id)
        file_path = self.download_dir / file_name
        
        # Ensure filename is unique if it exists
        counter = 1
        original_name = file_path.name
        while file_path.exists():
            stem = Path(original_name).stem
            suffix = Path(original_name).suffix
            file_path = self.download_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        fh = io.FileIO(file_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            
        return file_path

    async def archive_file(self, file_id: str):
        """Move the file to the processed folder if configured."""
        if not self.settings.gdrive_processed_folder_id:
            return

        # Retrieve the existing parents to remove
        file = self.service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents"))
        
        # Add the new parent and remove the old ones
        self.service.files().update(
            fileId=file_id,
            addParents=self.settings.gdrive_processed_folder_id,
            removeParents=previous_parents,
            fields="id, parents"
        ).execute()
        logger.info("Archived Google Drive file", file_id=file_id, folder_id=self.settings.gdrive_processed_folder_id)

    async def run_once(self):
        """Single polling cycle."""
        try:
            if not self.service:
                await self.connect()

            files = await self.list_new_files()
            if not files:
                return

            logger.info("Found potential receipts in Google Drive", count=len(files))
            
            for f in files:
                file_id = f.get("id")
                file_name = f.get("name")
                
                # Download to check hash (Drive md5Checksum can also be used, but we stick to our pipeline)
                file_path = await self.download_file(file_id, file_name)
                
                try:
                    result = await process_receipt(str(file_path), self.settings, self.bexio, self.db)
                    status = result.get("status")
                    logger.info("Google Drive processing finished", file=file_name, status=status)
                    
                    if status in ["booked", "duplicate"]:
                        await self.archive_file(file_id)
                        # Optionally delete local file if successfully booked or duplicate
                        if file_path.exists():
                            file_path.unlink()
                except Exception as e:
                    logger.error("Error processing Google Drive file", file=file_name, error=str(e))
        except Exception as e:
            logger.error("Google Drive polling error", error=str(e))

async def watch_gdrive(settings: Settings):
    """Periodically check Google Drive for new receipts."""
    if not settings.gdrive_credentials_file:
        logger.error("Google Drive credentials file is not set.")
        return

    async with BexioClient(
        token=settings.bexio_api_token, 
        base_url=settings.bexio_base_url
    ) as bexio:
        await bexio.cache_lookups()
        ingestor = GoogleDriveIngestor(settings, bexio)
        logger.info("Starting Google Drive watcher", interval=settings.gdrive_poll_interval)
        
        while True:
            await ingestor.run_once()
            await asyncio.sleep(settings.gdrive_poll_interval)
