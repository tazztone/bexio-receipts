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
from .vllm_server import start_vllm_server


class VisionExtraction(BaseModel):
    """Schema for Qwen3.6 vision-language extraction."""

    merchant_name: str | None = Field(None, description="Name of the vendor/store")
    transaction_date: str | None = Field(None, description="ISO date YYYY-MM-DD")
    currency: str = Field("CHF", description="3-letter currency code")
    subtotal_excl_vat: float | None = Field(None, description="Total net amount")
    vat_rate_pct: float | None = Field(None, description="Primary VAT rate (%)")
    vat_amount: float | None = Field(None, description="Primary VAT amount")
    total_incl_vat: float | None = Field(None, description="Grand total amount")
    vat_rows: list[dict] = Field(
        default_factory=list, description="List of all VAT lines"
    )
    account_assignments: list[AccountAssignment] = Field(
        default_factory=list, description="Suggested booking accounts per VAT rate"
    )
    confidence: float = Field(
        0.95, ge=0, le=1, description="Estimated extraction confidence"
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

    def _render_pdf_to_images(self, file_path: str, max_pages: int = 5) -> list[str]:
        """Render the first few pages of a PDF to base64 images at 150 DPI."""
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
                # 150 DPI (150/72 = 2.0833x zoom)
                zoom = 150 / 72
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
            extra_flags = [
                "--max-model-len",
                str(settings.vision_max_model_len),
                "--gpu-memory-utilization",
                str(settings.vision_gpu_memory_utilization),
                "--max-num-seqs",
                str(settings.vision_max_num_seqs),
                "--tensor-parallel-size",
                str(settings.vision_tensor_parallel_size),
                "--served-model-name",
                settings.vision_served_name,
            ]

            if settings.vision_quantization and settings.vision_quantization != "auto":
                extra_flags.extend(["--quantization", settings.vision_quantization])

            if (
                settings.vision_reasoning_parser
                and settings.vision_reasoning_parser.lower() != "none"
            ):
                extra_flags.extend([
                    "--reasoning-parser",
                    settings.vision_reasoning_parser,
                ])

            if (
                settings.vision_speculative_config
                and settings.vision_speculative_config.lower() != "none"
            ):
                extra_flags.extend([
                    "--speculative-config",
                    settings.vision_speculative_config,
                ])

            if settings.vision_enable_expert_parallel:
                extra_flags.append("--enable-expert-parallel")

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
            base64_images = self._render_pdf_to_images(file_path)
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

        accounts_context = "\n".join([
            f"- {acc_id}: {desc}" for acc_id, desc in settings.bexio_accounts.items()
        ])
        vat_context = f"Default VAT rate is {settings.default_vat_rate}%."

        system_prompt = (
            "You are a Swiss bookkeeping specialist. Extract data from the receipt image.\n\n"
            "### RULES ###\n"
            "1. MERCHANT: Vendor name (TOP logo/header).\n"
            "2. DATE: YYYY-MM-DD.\n"
            "3. TOTAL: Grand total.\n"
            "4. VAT ROWS: For each MWST line, extract Rate%, VAT_Amount, Net_Amount, Total_Amount.\n"
            "5. ACCOUNTS: Assign booking accounts based on product context.\n"
            f"AVAILABLE ACCOUNTS:\n{accounts_context}\n"
            f"{vat_context}\n"
            "6. CONFIDENCE: Estimate your certainty (0.0 to 1.0).\n"
        )

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
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_extraction",
                        "strict": False,
                        "schema": VisionExtraction.model_json_schema(),
                    },
                },
                max_tokens=4096,
            )

            raw_response_content = response.choices[0].message.content or ""
            try:
                # vLLM with json_schema should return pure JSON, but we guard against preambles
                json_start = raw_response_content.find("{")
                json_end = raw_response_content.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    json_str = raw_response_content[json_start:json_end]
                else:
                    json_str = raw_response_content

                data = json.loads(json_str)
                ext = VisionExtraction(**data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(
                    "vision_parsing_failed", error=str(e), content=raw_response_content
                )
                raise ValueError(f"Failed to parse VLM output as JSON: {e}") from e

            trace = ExtractionTrace(
                ocr_text=f"Vision extraction: {ext.merchant_name} on {ext.transaction_date}",
                step1_output=data,
            )

            return ProcessingResult(
                raw_text=f"Vision extraction from {file_path}",
                merchant_name=ext.merchant_name,
                transaction_date=ext.transaction_date,
                currency=ext.currency,
                subtotal_excl_vat=ext.subtotal_excl_vat,
                vat_rate_pct=ext.vat_rate_pct,
                vat_amount=ext.vat_amount,
                total_incl_vat=ext.total_incl_vat,
                vat_rows=[
                    RawVatRow(**r) if isinstance(r, dict) else r for r in ext.vat_rows
                ],
                account_assignments=ext.account_assignments,
                confidence=ext.confidence,
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

        # Convert Receipt back to RawVatRows for unified interface if needed
        # Actually, extract_receipt already has vat_rows in its intermediate steps
        # But we can reconstruct it or just pass receipt_obj fields

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
