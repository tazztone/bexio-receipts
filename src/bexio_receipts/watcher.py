"""
Folder filesystem monitoring for new receipt files.
Triggers the ingestion pipeline when new files are detected.
"""
import asyncio
import os
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    DirCreatedEvent,
    FileModifiedEvent,
    DirModifiedEvent,
)

import structlog

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)


class ReceiptHandler(FileSystemEventHandler):
    """Handles file creation events in the watched directory."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, settings: Settings, bexio: BexioClient
    ):
        self.loop = loop
        self.settings = settings
        self.bexio = bexio
        self.processing: set[Path] = set()
        self.db = DuplicateDetector(settings.database_path)

    def on_created(self, event: FileCreatedEvent | DirCreatedEvent):
        if event.is_directory:
            return
        self._trigger_processing(event.src_path)

    def on_modified(self, event: FileModifiedEvent | DirModifiedEvent):
        if event.is_directory:
            return
        self._trigger_processing(event.src_path)

    def _trigger_processing(self, src_path):
        if isinstance(src_path, bytes):
            src_path = src_path.decode()

        file_path = Path(src_path)
        # Check if it's an image or PDF
        if file_path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".pdf"]:
            logger.debug("Ignoring non-receipt file", path=str(file_path))
            return

        if file_path in self.processing:
            return

        logger.info(
            "File activity detected, scheduling processing", path=str(file_path)
        )
        self.processing.add(file_path)

        # Schedule the async processing on the main loop
        asyncio.run_coroutine_threadsafe(self._safe_process(file_path), self.loop)

    async def _wait_for_file_stabilization(self, file_path: Path, timeout: int = 10):
        """Poll file size until it stops changing."""
        last_size = -1
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                current_size = os.path.getsize(file_path)
                if current_size == last_size and current_size > 0:
                    return True
                last_size = current_size
            except OSError:
                # File might not be accessible yet
                pass
            await asyncio.sleep(0.5)
        return False

    async def _safe_process(self, file_path: Path):
        """Wrapper to handle errors and clean up state."""
        try:
            # Robust wait for file to be fully written
            if not await self._wait_for_file_stabilization(file_path):
                logger.warning(
                    "File stabilization timeout, attempting process anyway",
                    path=str(file_path),
                )

            result = await process_receipt(
                str(file_path), self.settings, self.bexio, self.db
            )
            logger.info(
                "Processing finished", path=str(file_path), status=result.get("status")
            )

        except Exception as e:
            logger.error("Error processing file", path=str(file_path), error=str(e))
        finally:
            self.processing.remove(file_path)


async def watch_folder(path: str, settings: Settings):
    """Starts the folder watcher."""
    path_obj = Path(path)
    if not path_obj.exists():
        logger.info("Creating watch directory", path=str(path_obj))
        path_obj.mkdir(parents=True, exist_ok=True)

    logger.info("Starting folder watcher", path=str(path_obj.absolute()))

    async with BexioClient(
        token=settings.bexio_api_token,
        base_url=settings.bexio_base_url,
        default_vat_rate=settings.default_vat_rate,
    ) as bexio:
        await bexio.cache_lookups()

        loop = asyncio.get_running_loop()
        event_handler = ReceiptHandler(loop, settings, bexio)
        observer = Observer()
        observer.schedule(event_handler, str(path_obj), recursive=True)
        observer.start()

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            observer.stop()
            logger.info("Stopping folder watcher")

        observer.join()
