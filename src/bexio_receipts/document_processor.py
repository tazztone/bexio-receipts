"""Document processing strategies: Vision (Qwen3.6) and OCR (GLM-OCR + LLM)."""

import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .config import Settings
from .extraction import (
    ExtractionTrace,
    classify_accounts,
    extract_receipt,
)
from .models import AccountAssignment, RawVatRow
from .ocr import async_run_ocr
from .vllm_server import build_vllm_flags, start_vllm_server


def extract_json_block(text: str) -> dict | None:
    """Extract and parse the first JSON code block or raw JSON string."""
    try:
        # Pre-strip whitespace and newlines
        text = text.strip()
        if not text:
            return None

        # Search for markdown blocks
        if "```json" in text:
            block = text.split("```json")[1].split("```", maxsplit=1)[0].strip()
        elif "```" in text:
            block = text.split("```")[1].split("```", maxsplit=1)[0].strip()
        else:
            # Fallback: look for the first '{' and last '}'
            start = text.find("{")
            end = text.rfind("}") + 1
            block = text[start:end] if start != -1 and end > start else text

        return json.loads(block)
    except (json.JSONDecodeError, IndexError) as e:
        logger.debug(
            "json_block_extraction_failed", error=str(e), text_preview=text[:100]
        )
        return None


class VisionExtraction(BaseModel):
    """Schema for Qwen3.6 vision-language extraction."""

    merchant_name: str | None = Field(None, description="Name of the vendor/store")
    transaction_date: str | None = Field(None, description="ISO date YYYY-MM-DD")
    currency: str = Field("CHF", description="3-letter currency code")
    subtotal_excl_vat: float | None = Field(None, description="Total net amount")
    vat_rate_pct: float | None = Field(None, description="Primary VAT rate (%)")
    vat_amount: float | None = Field(None, description="Primary VAT amount")
    total_incl_vat: float | None = Field(None, description="Grand total amount")
    vat_rows: list[RawVatRow] = Field(
        default_factory=list, description="List of all VAT lines"
    )
    account_assignments: list[AccountAssignment] = Field(
        default_factory=list, description="Suggested booking accounts per VAT rate"
    )


logger = structlog.get_logger(__name__)


class ProcessingResult(BaseModel):
    """Unified output from any document processor."""

    raw_text: str
    merchant_name: str | None = None
    transaction_date: str | None = None
    currency: str = "CHF"
    subtotal_excl_vat: float | None = None
    vat_rate_pct: float | None = None
    vat_amount: float | None = None
    total_incl_vat: float | None = None
    payment_method: str | None = None
    vat_rows: list[RawVatRow] = []
    account_assignments: list[AccountAssignment] = []
    confidence: float
    trace: ExtractionTrace


class DocumentProcessor(ABC):
    @abstractmethod
    async def process(
        self,
        file_path: str,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> ProcessingResult:
        pass


class VisionProcessor(DocumentProcessor):
    """Single-pass Vision-Language Model extraction using Qwen3.6."""

    def _encode_image(self, file_path: str) -> str:
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _render_pdf_to_images(self, file_path: str, settings: Settings) -> list[str]:
        """Render the first few pages of a PDF to base64 images at configured DPI."""
        max_pages = settings.vision_pdf_max_pages
        dpi = settings.vision_pdf_dpi
        images = []
        with pymupdf.open(file_path) as doc:
            if doc.page_count == 0:
                raise ValueError("PDF has no pages")

            if doc.page_count > max_pages:
                logger.warning(
                    "PDF has many pages, only processing the first few",
                    total=doc.page_count,
                    limit=max_pages,
                )

            for i in range(min(doc.page_count, max_pages)):
                page = doc[i]
                # Dynamic DPI
                zoom = dpi / 72
                matrix = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix)
                img_data = pix.tobytes("png")
                images.append(base64.b64encode(img_data).decode("utf-8"))
        return images

    async def process(
        self,
        file_path: str,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> ProcessingResult:
        if settings.vision_manage_server:
            extra_flags = build_vllm_flags(settings)
            await start_vllm_server(
                settings.vision_model,
                settings.vision_api_port,
                settings,
                extra_flags=extra_flags,
            )

        file_ext = Path(file_path).suffix.lower()
        is_pdf = file_ext == ".pdf"

        content: list[Any] = []
        if is_pdf:
            base64_images = self._render_pdf_to_images(file_path, settings)
            for img in base64_images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img}"},
                })
        else:
            base64_image = self._encode_image(file_path)
            mime = "image/jpeg" if file_ext in [".jpg", ".jpeg"] else "image/png"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64_image}"},
            })

        content.append({
            "type": "text",
            "text": "Extract all structured data from this receipt. If multiple pages, combine into one result.",
        })

        from .prompts import build_vision_system_prompt

        system_prompt = build_vision_system_prompt(settings)

        openai_client = AsyncOpenAI(
            base_url=f"http://{settings.vision_api_host}:{settings.vision_api_port}/v1",
            api_key="EMPTY",
            http_client=client,
        )

        try:
            logger.info(
                "Vision extraction started", file=file_path, model=settings.vision_model
            )
            response = await openai_client.chat.completions.create(
                model=settings.vision_served_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                temperature=settings.vision_temperature,
                frequency_penalty=settings.vision_frequency_penalty,
                max_tokens=settings.vision_max_tokens,
            )

            raw_response_content = response.choices[0].message.content or ""
            try:
                # Use robust extraction logic for markdown blocks
                logger.debug("vlm_raw_response", content=raw_response_content)
                data = extract_json_block(raw_response_content)
                if not data:
                    # Fallback to direct parse if no block found
                    data = json.loads(raw_response_content)

                ext = VisionExtraction(**data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(
                    "vision_parsing_failed", error=str(e), content=raw_response_content
                )
                raise ValueError(f"Failed to parse VLM output as JSON: {e}") from e

            trace = ExtractionTrace(
                ocr_text=raw_response_content,
                step1_output=data,
                step1_raw=raw_response_content,
                step3_assignments=[a.model_dump() for a in ext.account_assignments],
            )

            return ProcessingResult(
                raw_text=raw_response_content,
                merchant_name=ext.merchant_name,
                transaction_date=ext.transaction_date,
                currency=ext.currency,
                subtotal_excl_vat=ext.subtotal_excl_vat,
                vat_rate_pct=ext.vat_rate_pct,
                vat_amount=ext.vat_amount,
                total_incl_vat=ext.total_incl_vat,
                vat_rows=ext.vat_rows,
                account_assignments=ext.account_assignments,
                confidence=1.0
                if ext.merchant_name
                and ext.transaction_date
                and ext.total_incl_vat
                and ext.vat_rows
                else 0.0,
                trace=trace,
            )
        finally:
            await openai_client.close()


class OcrProcessor(DocumentProcessor):
    """Legacy multi-step OCR + LLM extraction pipeline."""

    async def process(
        self,
        file_path: str,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> ProcessingResult:
        # 1. Run OCR
        raw_text, confidence, _ = await async_run_ocr(file_path, settings)

        # 2. Extract structured data (Step 1 & 2)
        receipt_obj, trace = await extract_receipt(raw_text, settings, client=client)

        # 3. Classify accounts (Step 3)
        assignments = await classify_accounts(
            receipt_obj, raw_text, settings, client=client, trace=trace
        )

        return ProcessingResult(
            raw_text=raw_text,
            merchant_name=receipt_obj.merchant_name,
            transaction_date=receipt_obj.transaction_date.isoformat()
            if receipt_obj.transaction_date
            else None,
            currency=receipt_obj.currency,
            total_incl_vat=receipt_obj.total_incl_vat,
            payment_method=receipt_obj.payment_method,
            vat_rows=[
                RawVatRow(
                    rate=e.rate,
                    col_a=e.vat_amount,
                    col_b=e.base_amount,
                    col_c=e.total_incl_vat,
                )
                for e in receipt_obj.vat_breakdown
            ],
            account_assignments=assignments,
            confidence=confidence,
            trace=trace,
        )


def get_processor(settings: Settings) -> DocumentProcessor:
    if settings.processor_mode == "vision":
        return VisionProcessor()
    return OcrProcessor()
