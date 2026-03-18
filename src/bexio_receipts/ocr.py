import base64
import httpx
import logging
from paddleocr import PaddleOCR
from typing import Tuple, List, Dict, Optional
from .config import Settings

# Disable paddleocr logging to keep CLI clean
logging.getLogger("ppocr").setLevel(logging.ERROR)

def run_paddle_ocr(file_path: str) -> Tuple[str, float, List[Dict]]:
    """
    Run OCR on a file using PaddleOCR PP-OCRv5.
    """
    ocr = PaddleOCR(
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
    )

    results = ocr.ocr(file_path)

    lines = []
    if results:
        for res in results:
            if res:
                for line in res:
                    text = line[1][0]
                    confidence = line[1][1]
                    lines.append({"text": text, "confidence": confidence})

    raw_text = "\n".join(l["text"] for l in lines)
    avg_confidence = sum(l["confidence"] for l in lines) / len(lines) if lines else 0.0
    
    return raw_text, avg_confidence, lines

async def run_glm_ocr(file_path: str, settings: Settings) -> Tuple[str, float, List[Dict]]:
    """
    Run OCR on a file using GLM-OCR via Ollama.
    """
    with open(file_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    async with httpx.AsyncClient(timeout=60.0) as client:
        payload = {
            "model": settings.glm_ocr_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Text Recognition:",
                    "images": [img_base64]
                }
            ],
            "stream": False
        }
        
        resp = await client.post(f"{settings.glm_ocr_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        raw_text = data["message"]["content"]
        # GLM-OCR via Ollama chat API doesn't easily provide confidence per word/line
        # Returning 1.0 as a placeholder for now. 
        # In a real scenario, we might want to check the logprobs if Ollama supports it for chat.
        avg_confidence = 0.95 
        
        # We don't have per-line detail here like PaddleOCR
        lines = [{"text": raw_text, "confidence": avg_confidence}]
        
        return raw_text, avg_confidence, lines

def run_ocr(file_path: str, settings: Optional[Settings] = None) -> Tuple[str, float, List[Dict]]:
    """
    Unified entry point for OCR. Note: run_glm_ocr is async.
    If settings.ocr_engine is "glm-ocr", this function will fail if not awaited or handled.
    Refactoring this to be more flexible.
    """
    # For backward compatibility and simple use in tests
    engine = settings.ocr_engine if settings else "paddleocr"
    
    if engine == "paddleocr":
        return run_paddle_ocr(file_path)
    else:
        # This will be handled in the async pipeline
        raise ValueError(f"OCR engine {engine} must be run via async_run_ocr")

async def async_run_ocr(file_path: str, settings: Settings) -> Tuple[str, float, List[Dict]]:
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
