import asyncio
import logging
import time
from pathlib import Path
from typing import Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

import structlog

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient

logger = structlog.get_logger(__name__)

class ReceiptHandler(FileSystemEventHandler):
    """Handles file creation events in the watched directory."""
    
    def __init__(self, loop: asyncio.AbstractEventLoop, settings: Settings):
        self.loop = loop
        self.settings = settings
        self.processing: Set[Path] = set()
        
    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
            
        file_path = Path(event.src_path)
        # Check if it's an image or PDF
        if file_path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".pdf"]:
            logger.debug(f"Ignoring non-receipt file: {file_path}")
            return
            
        if file_path in self.processing:
            return
            
        logger.info(f"New file detected: {file_path}. Scheduling processing...")
        self.processing.add(file_path)
        
        # Schedule the async processing on the main loop
        asyncio.run_coroutine_threadsafe(
            self._safe_process(file_path), 
            self.loop
        )

    async def _safe_process(self, file_path: Path):
        """Wrapper to handle errors and clean up state."""
        try:
            # Wait a bit for the file to be fully written (if needed)
            await asyncio.sleep(1)
            
            bexio = BexioClient(
                token=self.settings.bexio_api_token, 
                base_url=self.settings.bexio_base_url
            )
            try:
                await bexio.cache_lookups()
                result = await process_receipt(str(file_path), self.settings, bexio)
                logger.info(f"Processing finished for {file_path}: {result.get('status')}")
            finally:
                await bexio.close()
                
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
        finally:
            self.processing.remove(file_path)

async def watch_folder(path: str, settings: Settings):
    """Starts the folder watcher."""
    path_obj = Path(path)
    if not path_obj.exists():
        logger.info(f"Creating watch directory: {path}")
        path_obj.mkdir(parents=True, exist_ok=True)
        
    logger.info(f"Starting folder watcher on {path_obj.absolute()}...")
    
    loop = asyncio.get_running_loop()
    event_handler = ReceiptHandler(loop, settings)
    observer = Observer()
    observer.schedule(event_handler, str(path_obj), recursive=False)
    observer.start()
    
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        observer.stop()
        logger.info("Stopping folder watcher...")
    
    observer.join()
