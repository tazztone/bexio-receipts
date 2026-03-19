import base64
import httpx
import logging
from functools import lru_cache
from paddleocr import PaddleOCR
from .config import Settings

import structlog

# Disable paddleocr logging to keep CLI clean
logging.getLogger("ppocr").setLevel(logging.ERROR)

logger = structlog.get_logger(__name__)


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


async def run_glm_ocr(
    file_path: str, settings: Settings
) -> tuple[str, float, list[dict]]:
    """
    Run OCR on a file using GLM-OCR via Ollama.
    """
    with open(file_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    async with httpx.AsyncClient(timeout=60.0) as client:
        prompt = (
            "Task: Information Extraction from Receipt\n"
            "Format: Output ONLY valid JSON according to this schema:\n"
            "{\n"
            '  "merchant_name": string or null,\n'
            '  "date": "YYYY-MM-DD" or null,\n'
            '  "total_incl_vat": number or null,\n'
            '  "vat_amount": number or null,\n'
            '  "vat_rate_pct": number or null,\n'
            '  "currency": "CHF",\n'
            '  "vat_breakdown": []\n'
            "}\n"
            "Instruction: Extract the merchant (e.g. Coop, Migros), the date, and the total amount. "
            "Swiss VAT rates are 8.1%, 2.6%, 3.8%. "
            "If a brand name like 'COOP' is visible, use it as merchant_name."
        )
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
        # Using 0.90 as a default.
        avg_confidence = 0.90

        # We don't have per-line detail here like PaddleOCR
        lines = [{"text": raw_text, "confidence": avg_confidence}]

        return raw_text, avg_confidence, lines


async def async_run_ocr(
    file_path: str, settings: Settings
) -> tuple[str, float, list[dict]]:
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
