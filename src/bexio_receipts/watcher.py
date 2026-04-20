"""
Folder filesystem monitoring for new receipt files.
Triggers the ingestion pipeline when new files are detected.
"""

import asyncio
import os
import time
from pathlib import Path

import structlog
from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from .bexio_client import BexioClient
from .config import Settings
from .database import DuplicateDetector
from .pipeline import process_receipt

logger = structlog.get_logger(__name__)
_gpu_semaphore = asyncio.Semaphore(1)
_background_tasks = set()


class ReceiptHandler(FileSystemEventHandler):
    """Handles file creation events in the watched directory."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, settings: Settings, bexio: BexioClient
    ):
        self.loop = loop
        self.settings = settings
        self.bexio = bexio
        self.processing: set[Path] = set()
        self._last_processed: dict[Path, float] = {}
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

        # Cooldown: skip if processed very recently (avoid double events)
        now = time.time()
        if file_path in self._last_processed:
            if now - self._last_processed[file_path] < 30:
                logger.debug(
                    "Skipping file within cooldown period", path=str(file_path)
                )
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
        start_time = asyncio.get_running_loop().time()

        while asyncio.get_running_loop().time() - start_time < timeout:
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

            async with _gpu_semaphore:
                result = await process_receipt(
                    str(file_path),
                    self.settings,
                    self.bexio,
                    self.db,
                    push_confirmed=False,
                )
            self._last_processed[file_path] = time.time()
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
        default_payment_terms_days=settings.default_payment_terms_days,
        push_enabled=settings.bexio_push_enabled,
    ) as bexio:
        try:
            await bexio.cache_lookups()
        except Exception as e:
            logger.warning(
                "Failed to connect to Bexio during watcher startup, proceeding anyway",
                error=str(e),
            )

        # Initial sweep: process existing files
        logger.info("Performing initial sweep of watch directory")
        db = DuplicateDetector(settings.database_path)
        for file_path in path_obj.glob("*"):
            if file_path.is_file() and file_path.suffix.lower() in [
                ".png",
                ".jpg",
                ".jpeg",
                ".pdf",
            ]:
                # Pre-filter duplicates before even scheduling
                file_hash = db.get_hash(str(file_path))
                if db.is_duplicate(file_hash):
                    logger.debug(
                        "Skipping known duplicate in initial sweep", path=str(file_path)
                    )
                    continue

                logger.info("Queuing existing file for processing", path=str(file_path))

                async def _queued_process(fp=file_path):
                    async with _gpu_semaphore:
                        await process_receipt(
                            str(fp), settings, bexio, db, push_confirmed=False
                        )
                        await asyncio.sleep(0.5)  # Let GPU/Ollama breathe between items

                        await asyncio.sleep(0.5)  # Let GPU/Ollama breathe between items

                task = asyncio.create_task(_queued_process())
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

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

        observer.join(timeout=5)
        if observer.is_alive():
            logger.warning("Observer thread did not stop cleanly within 5s")
