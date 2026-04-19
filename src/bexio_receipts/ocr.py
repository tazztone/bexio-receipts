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


def extract_pdf_text(file_path: str) -> str | None:
    """
    Extract text directly from a digital PDF using pdfplumber.
    Returns None if the extracted text is too short (likely a scanned image).
    """
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        full_text = "\n".join(text_parts).strip()
        # If less than 20 chars, it's likely just an image or garbled
        if len(full_text) > 20:
            return full_text
    except Exception as e:
        logger.warning("PDF text extraction failed", error=str(e), path=file_path)

    return None


async def run_glm_ocr(
    file_path: str | None,
    settings: Settings,
    client: httpx.AsyncClient,
    image_data: bytes | None = None,
    already_optimized: bool = False,
) -> tuple[str, float, list[dict]]:
    """
    Run OCR on a file using GLM-OCR via Ollama.
    """
    if already_optimized and image_data:
        # Caller already optimized and provided bytes (e.g. PDF loop)
        img_base64 = base64.b64encode(image_data).decode("utf-8")
    elif image_data:
        # Decode bytes, optimize, and re-encode to WebP for model
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

    prompt = "Text Recognition:"
    payload = {
        "model": settings.glm_ocr_model,
        "messages": [{"role": "user", "content": prompt, "images": [img_base64]}],
        "stream": False,
    }

    # Use the injected client with its configured timeouts
    resp = await client.post(f"{settings.glm_ocr_url}/api/chat", json=payload)
    resp.raise_for_status()
    data = resp.json()

    raw_text = data["message"]["content"]
    # GLM-OCR via Ollama chat API doesn't easily provide confidence per word/line
    # Using 0.90 as a default, downgrade to 0.50 if output is suspiciously short
    avg_confidence = 0.90 if len(raw_text) > 50 else 0.50

    # We don't have per-line detail here like PaddleOCR
    lines = [{"text": raw_text, "confidence": avg_confidence}]

    return raw_text, avg_confidence, lines


async def async_run_ocr(
    file_path: str, settings: Settings
) -> tuple[str, float, list[dict]]:

    is_pdf = str(file_path).lower().endswith(".pdf")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0, read=settings.glm_ocr_timeout, write=5.0, pool=2.0
        )
    ) as client:
        if is_pdf:
            extracted_text = extract_pdf_text(file_path)
            if extracted_text:
                logger.info(
                    "Successfully extracted text directly from PDF", path=file_path
                )
                return (
                    extracted_text,
                    1.0,
                    [{"text": extracted_text, "confidence": 1.0}],
                )

            logger.info("PDF appears to be scanned, using GLM-OCR", path=file_path)
            from pdf2image import convert_from_path

            # Convert all pages of scanned PDF to images for vision model
            try:
                images = convert_from_path(file_path, dpi=300)

                sem = asyncio.Semaphore(2)  # Limit concurrent OCR calls to save RAM

                async def _process_page(img, i):
                    async with sem:
                        img = _optimize_image(img)
                        buf = io.BytesIO()
                        img.save(buf, format="WEBP", quality=90)
                        logger.info(
                            f"Processing PDF page {i + 1}/{len(images)}",
                            path=file_path,
                        )
                        page_text, _, _ = await run_glm_ocr(
                            None,
                            settings,
                            client,
                            image_data=buf.getvalue(),
                            already_optimized=True,
                        )
                        return page_text

                # Parallel processing with asyncio.gather, limited by semaphore
                texts = await asyncio.gather(*[
                    _process_page(img, i) for i, img in enumerate(images)
                ])

                combined_text = "\n---PAGE BREAK---\n".join(texts)
                return (
                    combined_text,
                    0.90,
                    [{"text": combined_text, "confidence": 0.90}],
                )
            except Exception as e:
                logger.warning(
                    f"Failed to convert scanned PDF to images: {e}. Falling back to raw file."
                )
                return await run_glm_ocr(file_path, settings, client)

        return await run_glm_ocr(file_path, settings, client)
