"""OCR layer using GLM-OCR SDK (PP-DocLayoutV3 + GLM-OCR vLLM backend)."""

import asyncio
import socket
import subprocess
import threading
import time
from functools import partial

import structlog
from glmocr import GlmOcr

from .config import Settings

logger = structlog.get_logger(__name__)

_ocr_parser: GlmOcr | None = None
_vllm_process: subprocess.Popen | None = None
_ocr_lock = threading.Lock()


def _is_port_open(host: str, port: int) -> bool:
    """Check if a port is open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _start_vllm_server(settings: Settings):
    """Start the vLLM server in the background."""
    global _vllm_process  # noqa: PLW0603
    if _is_port_open(settings.glm_ocr_api_host, settings.glm_ocr_api_port):
        logger.info(
            "OCR API port already open, skipping vLLM startup",
            port=settings.glm_ocr_api_port,
        )
        return

    cmd = [
        "uv",
        "run",
        "vllm",
        "serve",
        "zai-org/GLM-OCR",
        "--port",
        str(settings.glm_ocr_api_port),
        "--max-model-len",
        str(settings.glm_ocr_vllm_max_model_len),
        "--max-num-seqs",
        str(settings.glm_ocr_vllm_max_num_seqs),
        "--gpu-memory-utilization",
        str(settings.glm_ocr_vllm_gpu_memory_utilization),
        "--served-model-name",
        "glm-ocr",
        "--trust-remote-code",
        "--speculative-config",
        '{"method": "mtp", "num_speculative_tokens": 3}',
    ]

    logger.info("Starting managed vLLM server", command=" ".join(cmd))
    _vllm_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give it a tiny bit of time to at least start the process
    time.sleep(1)


def get_ocr_parser(settings: Settings) -> GlmOcr:
    """Get or create the long-lived GlmOcr parser instance."""
    global _ocr_parser  # noqa: PLW0603
    with _ocr_lock:
        if _ocr_parser is None:
            if settings.glm_ocr_manage_server:
                _start_vllm_server(settings)

            logger.info(
                "Initializing OCR parser (singleton)",
                host=settings.glm_ocr_api_host,
                port=settings.glm_ocr_api_port,
            )
            _ocr_parser = GlmOcr(
                mode="selfhosted",
                model="glm-ocr",
                ocr_api_host=settings.glm_ocr_api_host,
                ocr_api_port=settings.glm_ocr_api_port,
                layout_device=settings.glm_ocr_layout_device,
                log_level="WARNING",
                # Pass deep config via _dotted to ensure it bypasses the SDK's limited keyword mapping
                _dotted={
                    "pipeline.ocr_api.connect_timeout": settings.glm_ocr_connect_timeout,
                    "pipeline.ocr_api.request_timeout": settings.glm_ocr_request_timeout,
                    "pipeline.page_loader.max_tokens": settings.glm_ocr_max_tokens,
                },
            )
            # Enter the context once for the lifetime of the process
            _ocr_parser.__enter__()
        return _ocr_parser


def close_ocr_parser():
    """Shutdown the OCR parser and release resources."""
    global _ocr_parser, _vllm_process  # noqa: PLW0603
    with _ocr_lock:
        if _ocr_parser is not None:
            logger.info("Closing OCR parser")
            try:
                _ocr_parser.__exit__(None, None, None)
            except Exception as e:
                logger.error("Error closing OCR parser", error=str(e))
            finally:
                _ocr_parser = None

        if _vllm_process is not None:
            logger.info("Terminating vLLM server")
            try:
                _vllm_process.terminate()
                _vllm_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("vLLM server didn't stop, killing it")
                _vllm_process.kill()
            except Exception as e:
                logger.error("Error terminating vLLM server", error=str(e))
            finally:
                _vllm_process = None


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
