"""
Unified OCR layer supporting multiple engines (PaddleOCR, GLM-4-V).
Responsible for extracting raw text from images and PDFs.
"""

import base64
import httpx
import logging
from functools import lru_cache
from paddleocr import PaddleOCR
from .config import Settings

import io
import structlog
from PIL import Image, ImageEnhance

# Disable paddleocr logging to keep CLI clean
logging.getLogger("ppocr").setLevel(logging.ERROR)

logger = structlog.get_logger(__name__)


def _optimize_image(img: Image.Image, max_long_edge: int = 2560) -> Image.Image:
    """Optimize image for speed: cap resolution and boost contrast."""
    # Resize if needed
    w, h = img.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Boost contrast for thermal receipts (mildly)
    img = ImageEnhance.Contrast(img).enhance(1.3)
    return img


@lru_cache(maxsize=1)
def get_paddle_ocr() -> PaddleOCR:
    """Instantiate and cache the PaddleOCR model to avoid 2-5s loading time per call."""
    return PaddleOCR()


def run_paddle_ocr(file_path: str) -> tuple[str, float, list[dict]]:
    """
    Run OCR on a file using PaddleOCR PP-OCRv5.
    """
    ocr = get_paddle_ocr()

    results = ocr.ocr(file_path)

    lines = []
    page_confidences = []

    if results:
        for res in results:
            if res:
                page_lines = []
                page_text_len = 0
                for line in res:
                    text = line[1][0]
                    confidence = line[1][1]
                    page_lines.append({"text": text, "confidence": confidence})
                    page_text_len += len(text)

                # Filter out near-blank pages (less than 10 characters) from confidence average
                if page_text_len >= 10:
                    page_avg = sum(item["confidence"] for item in page_lines) / len(
                        page_lines
                    )
                    page_confidences.append(page_avg)

                lines.extend(page_lines)

    raw_text = "\n".join(line["text"] for line in lines)

    if page_confidences:
        avg_confidence = sum(page_confidences) / len(page_confidences)
    else:
        # Fallback if all pages were near-blank or no results
        avg_confidence = (
            sum(line["confidence"] for line in lines) / len(lines) if lines else 0.0
        )

    return raw_text, avg_confidence, lines


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
    file_path: str | None, settings: Settings, image_data: bytes | None = None
) -> tuple[str, float, list[dict]]:
    """
    Run OCR on a file using GLM-OCR via Ollama.
    """
    if image_data:
        # Decode bytes, optimize, and re-encode to WebP for model
        with Image.open(io.BytesIO(image_data)) as img:
            img = _optimize_image(img)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=90)
            img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    elif file_path:
        with Image.open(file_path) as img:
            img = _optimize_image(img)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=90)
            img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    else:
        raise ValueError("Either file_path or image_data must be provided")

    async with httpx.AsyncClient(timeout=60.0) as client:
        prompt = "Text Recognition:"
        payload = {
            "model": settings.glm_ocr_model,
            "messages": [{"role": "user", "content": prompt, "images": [img_base64]}],
            "stream": False,
        }

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
    import mimetypes

    mime_type, _ = mimetypes.guess_type(file_path)

    if mime_type == "application/pdf" or str(file_path).lower().endswith(".pdf"):
        extracted_text = extract_pdf_text(file_path)
        if extracted_text:
            logger.info("Successfully extracted text directly from PDF", path=file_path)
            return extracted_text, 1.0, [{"text": extracted_text, "confidence": 1.0}]
        else:
            logger.info(
                f"PDF appears to be scanned, falling back to {settings.ocr_engine}",
                path=file_path,
            )
            if settings.ocr_engine == "paddleocr":
                import asyncio
                from functools import partial

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, partial(run_paddle_ocr, file_path)
                )
            elif settings.ocr_engine == "glm-ocr":
                from pdf2image import convert_from_path
                import io

                # Convert all pages of scanned PDF to images for vision model
                try:
                    images = convert_from_path(file_path, dpi=300)
                    texts = []
                    for i, img in enumerate(images):
                        img = _optimize_image(img)
                        buf = io.BytesIO()
                        img.save(buf, format="WEBP", quality=90)
                        logger.info(
                            f"Processing PDF page {i + 1}/{len(images)}", path=file_path
                        )
                        page_text, _, _ = await run_glm_ocr(
                            None, settings, image_data=buf.getvalue()
                        )
                        texts.append(page_text)

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
                    return await run_glm_ocr(file_path, settings)
            else:
                return await run_glm_ocr(file_path, settings)

    if settings.ocr_engine == "paddleocr":
        # PaddleOCR is sync, wrap in thread to not block loop
        import asyncio
        from functools import partial

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(run_paddle_ocr, file_path))
    elif settings.ocr_engine == "glm-ocr":
        return await run_glm_ocr(file_path, settings)
    else:
        raise ValueError(f"Unsupported OCR engine: {settings.ocr_engine}")
