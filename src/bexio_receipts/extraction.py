"""
LLM-powered structured extraction using Pydantic AI.
Transforms raw OCR text into validated receipt data models.
"""

import asyncio
from typing import Any

import httpx
import structlog
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
from .models import Receipt

logger = structlog.get_logger(__name__)


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

        output_type: type[Any] = str
        if use_structured:
            output_type = (
                NativeOutput(Receipt)
                if settings.llm_provider == "openrouter"
                else Receipt
            )

        agent = Agent(
            model,
            output_type=output_type,
            retries=0,  # Disabled for development debugging. In production, use 1 or 3.
            system_prompt=(
                "Extract receipt data from OCR text. Output a structured Receipt model.\n"
                "### CRITICAL RULES ###\n"
                "1. MERCHANT: Extract the STORE or VENDOR name (e.g. 'Prodega Markt', 'Coop', 'Migros'). "
                "IGNORE the customer/buyer address block (e.g. 'OHNI GmbH').\n"
                "2. SWISS VAT: Rates are 8.1% (std), 2.6% (red), 3.8% (acc). "
                "If multiple rates are present, breakdown into 'vat_breakdown'.\n"
                "3. MATH: 'vat_amount' in breakdown MUST be the difference between inkl. and exkl. MWST. "
                "'base_amount' is the exkl. MWST value. "
                "Top-level 'vat_amount' MUST exactly equal the SUM of the breakdown vat_amounts (or Total Inkl - Subtotal Exkl). "
                "Line item 'total' MUST be the EXKL. MWST amount (Base) to match the subtotal.\n"
                "4. VAT TABLE MATH (non-negotiable): Column order varies! In Prodega receipts, order is: [VAT_AMOUNT] [BASE_AMOUNT] [TOTAL_INCL]. "
                "Example: '4.59 176.70 181.29' -> vat=4.59, base=176.70, total=181.29. "
                "Always verify base_amount + vat_amount = total_incl_vat before assigning. NEVER swap them incorrectly.\n"
                "5. DATE: The date is often inline (e.g., 'Datum: 31.01.2026 Ihr Betrag: 214.20'). Extract '2026-01-31'.\n"
                "6. CURRENCY: Always use 'CHF' unless a different currency is clearly the primary total.\n"
                "7. PAYMENT: Detect 'cash' if 'Bar' is mentioned, else 'card' or null.\n"
                "8. CONFIDENCE: Ignore 'Sie sparen' (savings) values when calculating VAT breakdown."
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
                                str(getattr(p, "content", p))
                                for p in raw_parts
                                if hasattr(p, "content") or isinstance(p, str)
                            )
                            if last_raw:
                                break

                if not use_structured:
                    cleaned = result.output.strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    if cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    try:
                        receipt = Receipt.model_validate_json(cleaned.strip())
                        return receipt, last_raw
                    except Exception as e:
                        logger.error(
                            "Failed to parse manual JSON fallback",
                            error=str(e),
                            raw=cleaned,
                        )
                        raise ExtractionError(
                            f"Failed to parse fallback JSON: {e!s}", last_raw=last_raw
                        ) from e

                return result.output, last_raw

            except (
                AgentRunError,
                UnexpectedModelBehavior,
                ValidationError,
                TimeoutError,
            ) as e:
                if messages:
                    # Find the last message that has parts (ModelResponse)
                    for msg in reversed(messages):
                        if hasattr(msg, "parts"):
                            raw_parts = getattr(msg, "parts", [])
                            last_raw = " | ".join(
                                str(getattr(p, "content", p))
                                for p in raw_parts
                                if hasattr(p, "content") or isinstance(p, str)
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
