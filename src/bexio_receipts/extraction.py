"""
LLM-powered structured extraction using Pydantic AI.
Transforms raw OCR text into validated receipt data models.
"""

import asyncio
from typing import Any

import httpx
import structlog
from dateutil import parser
from pydantic import ValidationError
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.exceptions import AgentRunError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer, OpenAIModelProfile
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .models import RawReceipt, RawVatRow, Receipt, VatEntry

logger = structlog.get_logger(__name__)


def resolve_vat_rows(rows: list[RawVatRow]) -> list[VatEntry]:
    entries = []
    for row in rows:
        a, b, c = row.col_a, row.col_b, row.col_c
        # Rule: base + vat = total. Try all column permutations.
        candidates = [(a, b, c), (b, a, c), (a, c, b)] if c is not None else [(a, b, None), (b, a, None)]
        resolved = False
        for vat, base, total in candidates:
            if total is not None:
                if abs(round(base + vat, 2) - total) < 0.02:
                    entries.append(VatEntry(rate=row.rate, vat_amount=vat, base_amount=base, total_incl_vat=total))
                    resolved = True
                    break
            else:
                # no third column — compute total
                if vat <= base:
                    entries.append(VatEntry(rate=row.rate, vat_amount=vat, base_amount=base))
                else:
                    entries.append(VatEntry(rate=row.rate, vat_amount=base, base_amount=vat))
                resolved = True
                break
        if not resolved:
            raise ValueError(f"Cannot resolve VAT columns for row: {row}")
    return entries


def assemble_receipt(raw: RawReceipt) -> Receipt:
    vat_entries = resolve_vat_rows(raw.vat_rows)

    if raw.total_incl_vat is not None and not vat_entries:
        logger.warning("Receipt has a total but no VAT rows were extracted", total=raw.total_incl_vat)
        raise ValueError("Receipt has a total but no VAT rows were extracted")

    parsed_date = None
    if raw.transaction_date:
        try:
            parsed_date = parser.parse(raw.transaction_date, dayfirst=True).date()
        except Exception as e:
            logger.warning("Could not parse date", raw_date=raw.transaction_date, error=str(e))

    return Receipt(
        merchant_name=raw.merchant_name,
        transaction_date=parsed_date,
        currency=raw.currency,
        total_incl_vat=raw.total_incl_vat,
        vat_breakdown=vat_entries,
        vat_amount=round(sum(e.vat_amount for e in vat_entries), 2) if vat_entries else None,
        subtotal_excl_vat=round(sum(e.base_amount for e in vat_entries), 2) if vat_entries else None,
        payment_method=raw.payment_method,
    )


class ExtractionError(Exception):
    """Custom exception that carries the raw model response for debugging."""

    def __init__(self, message: str, last_raw: str | None = None):
        super().__init__(message)
        self.last_raw = last_raw


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        httpx.HTTPStatusError,
        ValidationError,
        ExtractionError,
    )),
    reraise=True,
)
async def extract_receipt(
    raw_text: str, settings: Settings, client: httpx.AsyncClient
) -> tuple[Receipt, str | None]:
    """
    Extract receipt data from OCR text using Pydantic AI.
    Returns (Receipt, last_raw_response).
    """
    or_client = None
    try:
        if settings.llm_provider == "ollama":
            base_url = settings.ollama_url.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"

            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OllamaProvider(base_url=base_url, http_client=client),
            )
        elif settings.llm_provider == "openai":
            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OpenAIProvider(http_client=client),
            )
        elif settings.llm_provider == "openrouter":
            from openai import AsyncOpenAI

            api_key = settings.openrouter_api_key
            if not api_key:
                raise ValueError(
                    "OPENROUTER_API_KEY is required for OpenRouter provider"
                )

            or_client = AsyncOpenAI(
                base_url=settings.openrouter_url,
                api_key=api_key,
                default_headers={
                    "HTTP-Referer": settings.openrouter_site_url,
                    "X-Title": settings.openrouter_site_name,
                },
            )
            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OpenAIProvider(openai_client=or_client),
                profile=OpenAIModelProfile(
                    supports_json_schema_output=True,
                    supports_json_object_output=True,
                    json_schema_transformer=OpenAIJsonSchemaTransformer,
                ),
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")

        # Structured output strategy
        use_structured = True
        system_prompt_suffix = ""
        if (
            settings.llm_provider == "openrouter"
            and not settings.openrouter_use_structured_output
        ):
            use_structured = False
            system_prompt_suffix = "\n\nCRITICAL: Return ONLY raw, valid JSON matching the required schema. Do not use markdown blocks (```json)."

        output_type: Any = str
        if use_structured:
            output_type = (
                NativeOutput(RawReceipt)
                if settings.llm_provider == "openrouter"
                else RawReceipt
            )

        agent = Agent(
            model,
            output_type=output_type,
            retries=0 if settings.env == "development" else 1,
            system_prompt=(
                "Transcribe the receipt data from OCR text into a structured model.\n"
                "### CRITICAL RULES ###\n"
                "1. MERCHANT: Extract the STORE or VENDOR name (e.g. 'Prodega Markt', 'Coop', 'Migros'). "
                "IGNORE the customer/buyer address block (e.g. 'OHNI GmbH').\n"
                "2. SWISS VAT: Transcribe VAT rows as you see them. Copy each number in the row in the exact order "
                "it appears from left to right (col_a, col_b, col_c). Do not compute anything. Do not reorder columns.\n"
                "3. DATE: Transcribe the transaction date exactly as it is written (e.g., '31.01.2026' or 'Datum: 31.01.2026').\n"
                "4. CURRENCY: Always use 'CHF' unless a different currency is clearly the primary total.\n"
                "5. PAYMENT: Detect 'cash' if 'Bar' is mentioned, else 'card' or null.\n"
                "6. CONFIDENCE: Ignore 'Sie sparen' (savings) values when extracting VAT breakdown."
                + system_prompt_suffix
            ),
        )

        logger.info(
            "LLM Request started",
            model=settings.llm_model,
            text_len=len(raw_text),
            timeout=settings.llm_timeout,
        )
        start_time = asyncio.get_event_loop().time()

        with capture_run_messages() as messages:
            last_raw = "Unavailable"
            try:
                result = await asyncio.wait_for(
                    agent.run(f"Receipt text:\n{raw_text}"),
                    timeout=settings.llm_timeout,
                )
                duration = asyncio.get_event_loop().time() - start_time
                logger.info(
                    "LLM Request completed",
                    model=settings.llm_model,
                    duration=round(duration, 2),
                )

                # Capture raw from messages for success as well
                if messages:
                    for msg in reversed(messages):
                        if hasattr(msg, "parts"):
                            raw_parts = getattr(msg, "parts", [])
                            last_raw = " | ".join(
                                getattr(p, "content", "") or getattr(p, "args_as_json_str", lambda: "")()
                                for p in raw_parts
                            )
                            if last_raw:
                                break

                if not use_structured:
                    cleaned = result.output.strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    cleaned = cleaned.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    cleaned = cleaned.strip()
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()
                    try:
                        raw_receipt = RawReceipt.model_validate_json(cleaned.strip())
                        try:
                            receipt = assemble_receipt(raw_receipt)
                        except ValueError as ve:
                            raise ExtractionError(f"VAT assembly failed: {ve}", last_raw=last_raw) from ve
                        return receipt, last_raw
                    except ExtractionError:
                        raise
                    except Exception as e:
                        logger.error(
                            "Failed to parse manual JSON fallback",
                            error=str(e),
                            raw=cleaned,
                        )
                        raise ExtractionError(
                            f"Failed to parse fallback JSON: {e!s}", last_raw=last_raw
                        ) from e

                assert isinstance(result.output, RawReceipt)
                try:
                    receipt = assemble_receipt(result.output)
                except ValueError as ve:
                    raise ExtractionError(f"VAT assembly failed: {ve}", last_raw=last_raw) from ve
                return receipt, last_raw

            except (
                AgentRunError,
                UnexpectedModelBehavior,
                ValidationError,
                TimeoutError,
                ValueError,
            ) as e:
                if messages:
                    # Find the last message that has parts (ModelResponse)
                    for msg in reversed(messages):
                        if hasattr(msg, "parts"):
                            raw_parts = getattr(msg, "parts", [])
                            last_raw = " | ".join(
                                getattr(p, "content", "") or getattr(p, "args_as_json_str", lambda: "")()
                                for p in raw_parts
                            )
                            if last_raw:
                                break

                logger.error(
                    "LLM extraction failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    last_raw=last_raw,
                    model=settings.llm_model,
                )
                raise ExtractionError(
                    f"LLM extraction failed: {e!s}", last_raw=last_raw
                ) from e

    finally:
        if or_client:
            await or_client.close()
