"""OCR layer using GLM-OCR SDK (PP-DocLayoutV3 + GLM-OCR vLLM backend)."""

import asyncio
import threading
from functools import partial

import structlog
from glmocr import GlmOcr

from .config import Settings

logger = structlog.get_logger(__name__)

_ocr_parser: GlmOcr | None = None
_ocr_lock = threading.Lock()


def get_ocr_parser(settings: Settings) -> GlmOcr:
    """Get or create the long-lived GlmOcr parser instance."""
    global _ocr_parser  # noqa: PLW0603
    with _ocr_lock:
        if _ocr_parser is None:
            logger.info(
                "Initializing OCR parser (singleton)",
                host=settings.glm_ocr_api_host,
                port=settings.glm_ocr_api_port,
            )
            _ocr_parser = GlmOcr(
                mode="selfhosted",
                ocr_api_host=settings.glm_ocr_api_host,
                ocr_api_port=settings.glm_ocr_api_port,
                layout_device=settings.glm_ocr_layout_device,
                log_level="WARNING",
                connect_timeout=settings.glm_ocr_connect_timeout,
                request_timeout=settings.glm_ocr_request_timeout,
            )
            # Enter the context once for the lifetime of the process
            _ocr_parser.__enter__()
        return _ocr_parser


def close_ocr_parser():
    """Shutdown the OCR parser and release resources."""
    global _ocr_parser  # noqa: PLW0603
    with _ocr_lock:
        if _ocr_parser is not None:
            logger.info("Closing OCR parser")
            try:
                _ocr_parser.__exit__(None, None, None)
            except Exception as e:
                logger.error("Error closing OCR parser", error=str(e))
            finally:
                _ocr_parser = None


def _sync_run_ocr(file_path: str, settings: Settings) -> tuple[str, float, list[dict]]:
    """Blocking GLM-OCR call — runs in thread pool."""
    logger.info("Starting sync OCR run", file=file_path)
    try:
        parser = get_ocr_parser(settings)
        result = parser.parse(file_path)

        markdown = result.markdown_result or ""
        # json_result: list[list[dict]] — per-page, per-region
        regions = result.json_result or []
        confidence = 0.90  # SDK doesn't expose per-token confidence

        flat_regions = [r for page in regions for r in page]
        metadata = [
            {
                "text": r.get("content", ""),
                "label": r.get("label", ""),
                "confidence": confidence,
            }
            for r in flat_regions
        ]

        if not metadata and markdown:
            metadata = [{"text": markdown, "confidence": confidence}]

        logger.info(
            "OCR completed successfully", file=file_path, regions_count=len(metadata)
        )
        return markdown, confidence, metadata
    except Exception as e:
        logger.error("OCR SDK call failed", error=str(e), file=file_path)
        raise


async def async_run_ocr(
    file_path: str,
    settings: Settings,
) -> tuple[str, float, list[dict]]:
    """
    Public OCR entry point. Runs blocking SDK in thread executor with timeout.
    Returns (markdown_text, confidence, region_metadata).
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, partial(_sync_run_ocr, file_path, settings)),
            timeout=settings.glm_ocr_timeout,
        )
    except TimeoutError:
        logger.error(
            "OCR request timed out", timeout=settings.glm_ocr_timeout, file=file_path
        )
        raise
