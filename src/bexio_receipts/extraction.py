"""
LLM-powered structured extraction using Pydantic AI.
Transforms raw OCR text into validated receipt data models.
"""

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tenacity import retry, stop_after_attempt, wait_exponential
from .models import Receipt
from .config import Settings
import structlog

logger = structlog.get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
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
                "The grand total is usually labelled 'Total Rechnung' or 'Total inkl. MWST'. "
                "Top-level 'vat_amount' is the SUM of breakdown amounts.\n"
                "4. MARKDOWN TABLES: The OCR text may contain Markdown tables (| col | col |). "
                "Parse them column by column. In the VAT summary table, columns are typically: "
                "Rate | Base (exkl.) | VAT amount | Total (inkl.).\n"
                "5. CURRENCY: Always use 'CHF' unless a different currency is clearly the primary total. "
                "Ignore conversion equivalents (e.g. Euro total at the bottom).\n"
                "6. PAYMENT: Detect 'cash' if 'Bar' is mentioned, else 'card' or null.\n"
                "7. CONFIDENCE: Ensure you clean up any OCR artifacts or hallucinations."
            ),
        )

        result = await agent.run(f"Receipt text:\n{raw_text}")
        return result.output
