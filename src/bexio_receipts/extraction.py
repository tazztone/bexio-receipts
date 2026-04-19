"""
LLM-powered structured extraction using Pydantic AI.
Transforms raw OCR text into validated receipt data models.
"""

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from pydantic import ValidationError
import asyncio
from .models import Receipt
from .config import Settings
import structlog

logger = structlog.get_logger(__name__)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, ValidationError)),
    reraise=True,
)
async def extract_receipt(raw_text: str, settings: Settings) -> Receipt:
    """
    Extract receipt data from OCR text using Pydantic AI.
    """
    # Add explicit timeout for httpx client
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        if settings.llm_provider == "ollama":
            base_url = settings.ollama_url.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"

            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OllamaProvider(base_url=base_url, http_client=http_client),
            )
        elif settings.llm_provider == "openai":
            # Assumes OPENAI_API_KEY is set in environment
            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OpenAIProvider(http_client=http_client),
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")

        agent = Agent(  # type: ignore[call-overload]
            model,
            output_type=Receipt,
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
                "4. VAT TABLE MATH (non-negotiable): For each VAT row, these three values appear: "
                "base_amount (exkl. MWST), vat_amount, total_incl_vat (inkl. MWST). "
                "They MUST satisfy: base_amount + vat_amount = total_incl_vat. "
                "Example: 176.70 + 4.59 = 181.29 -> base=176.70, vat=4.59, total=181.29. "
                "If your assignment fails this check, swap the values until it holds. "
                "NEVER assign the inkl. MWST total as the base_amount.\n"
                "5. CURRENCY: Always use 'CHF' unless a different currency is clearly the primary total. "
                "Ignore conversion equivalents (e.g. Euro total at the bottom).\n"
                "6. PAYMENT: Detect 'cash' if 'Bar' is mentioned, else 'card' or null.\n"
                "7. CONFIDENCE: Ensure you clean up any OCR artifacts or hallucinations."
            ),
        )

        # Total timeout for the entire LLM round-trip
        result = await asyncio.wait_for(
            agent.run(f"Receipt text:\n{raw_text}"), timeout=120
        )
        return result.output
