"""
Unified OCR layer using GLM-OCR via Ollama.
Responsible for extracting raw text from images and PDFs.
"""

import asyncio
import base64
import io

import httpx
import structlog
from PIL import Image, ImageEnhance
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings

logger = structlog.get_logger(__name__)


def _optimize_image(img: Image.Image, max_long_edge: int = 2560) -> Image.Image:
    """Optimize image for speed: cap resolution and boost contrast."""
    # Resize if needed
    w, h = img.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    # Boost contrast for thermal receipts (mildly)
    img = ImageEnhance.Contrast(img).enhance(1.3)
    return img


async def run_glm_ocr(
    file_path: str | None,
    settings: Settings,
    client: httpx.AsyncClient,
    image_data: bytes | None = None,
    already_optimized: bool = False,
    prompt: str = "Text Recognition:",
) -> tuple[str, float, list[dict]]:
    """
    Run OCR using GLM-OCR model via Ollama.
    Returns (text, average_confidence, line_metadata).
    """
    if already_optimized and image_data:
        # Caller already optimized and provided bytes
        img_base64 = base64.b64encode(image_data).decode("utf-8")
    elif image_data:
        # Decode bytes, optimize, and re-encode
        with Image.open(io.BytesIO(image_data)) as img:
            optimized_img = _optimize_image(img)
            buf = io.BytesIO()
            optimized_img.save(buf, format="WEBP", quality=90)
            img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    elif file_path:
        with Image.open(file_path) as img:
            optimized_img = _optimize_image(img)
            buf = io.BytesIO()
            optimized_img.save(buf, format="WEBP", quality=90)
            img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    else:
        raise ValueError("Either file_path or image_data must be provided")

    payload = {
        "model": settings.glm_ocr_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [img_base64],
            }
        ],
        "stream": False,
    }

    # Use AsyncRetrying to handle transient Ollama failures
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
        reraise=True,
    ):
        with attempt:
            resp = await client.post(f"{settings.glm_ocr_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["message"]["content"]

    return raw_text, 0.90, [{"text": raw_text, "confidence": 0.90}]


async def _do_async_run_ocr(
    file_path: str, settings: Settings, client: httpx.AsyncClient
) -> tuple[str, float, list[dict]]:
    """Internal implementation of OCR runner with pass merging."""
    # Check if it's a PDF
    if file_path.lower().endswith(".pdf"):
        import pymupdf

        try:
            doc = pymupdf.open(file_path)
            full_text = ""
            total_conf = 0.0
            page_count = 0

            for page in doc:
                page_count += 1
                pix = page.get_pixmap(dpi=200)
                img_data = pix.tobytes("webp")
                text, conf, _ = await run_glm_ocr(
                    None, settings, client, image_data=img_data
                )
                full_text += text + "\n"
                total_conf += conf

            avg_conf = total_conf / page_count if page_count > 0 else 0
            return full_text, avg_conf, [{"text": full_text, "confidence": avg_conf}]
        except Exception as e2:
            raise RuntimeError(f"OCR failed for PDF: {e2}") from e2

    # --- TWO-PASS STRATEGY FOR IMAGES (Option B) ---
    try:
        with Image.open(file_path) as img:
            optimized = _optimize_image(img)
            w, h = optimized.size

            # Pass 1: full image, text recognition
            logger.info("OCR Pass 1: Full text recognition", path=file_path)
            buf = io.BytesIO()
            optimized.save(buf, format="WEBP", quality=90)
            text_result, conf1, _ = await run_glm_ocr(
                None,
                settings,
                client,
                image_data=buf.getvalue(),
                already_optimized=True,
                prompt="Text Recognition:",
            )
            logger.debug("Pass 1 result length", length=len(text_result))

            # Pass 2: bottom 40% crop, table recognition
            table_result = ""
            conf2 = conf1
            try:
                logger.info("OCR Pass 2: Bottom crop table recognition", path=file_path)
                if settings.glm_ocr_inter_pass_delay > 0:
                    await asyncio.sleep(settings.glm_ocr_inter_pass_delay)

                table_region = optimized.crop((0, int(h * 0.60), w, h))
                buf2 = io.BytesIO()
                table_region.save(buf2, format="WEBP", quality=90)
                table_result, conf2, _ = await run_glm_ocr(
                    None,
                    settings,
                    client,
                    image_data=buf2.getvalue(),
                    already_optimized=True,
                    prompt="Table Recognition:",
                )
                logger.debug("Pass 2 result length", length=len(table_result))
            except Exception as e:
                logger.warning("Pass 2 table OCR failed, using text-only", error=str(e))

            combined_text = (
                f"{text_result}\n\n--- VAT TABLE (structured) ---\n{table_result}"
            )
            avg_conf = (conf1 + conf2) / 2
            return (
                combined_text,
                avg_conf,
                [{"text": combined_text, "confidence": avg_conf}],
            )
    except Exception as e:
        logger.error("Two-pass OCR failed, falling back to single pass", error=str(e))
        return await run_glm_ocr(file_path, settings, client)


async def async_run_ocr(
    file_path: str, settings: Settings, client: httpx.AsyncClient | None = None
) -> tuple[str, float, list[dict]]:
    """
    Public entry point for OCR.
    Handles client lifecycle if none provided.
    """
    if client:
        return await _do_async_run_ocr(file_path, settings, client)

    async with httpx.AsyncClient(timeout=60.0) as new_client:
        return await _do_async_run_ocr(file_path, settings, new_client)
