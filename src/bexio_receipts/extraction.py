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
    reraise=True
)
async def extract_receipt(raw_text: str, settings: Settings) -> Receipt:
    """
    Extract receipt data from OCR text using Pydantic AI.
    """
    # Add explicit timeout for httpx client
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        if settings.llm_provider == "ollama":
            base_url = settings.glm_ocr_url.rstrip("/")
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

        agent = Agent(
            model,
            result_type=Receipt,
            system_prompt=(
                "Extract receipt data from OCR text. Swiss VAT rates are: "
                "8.1% (standard), 2.6% (reduced — food, books), 3.8% (accommodation). "
                "Return null for fields not found. "
                "IMPORTANT: If the receipt shows multiple VAT rates, extract the detailed "
                "breakdown into the 'vat_breakdown' field (rate, base_amount, vat_amount). "
                "The 'vat_rate_pct' and 'vat_amount' should represent the dominant rate "
                "found on the receipt. "
                "Ensure the total_incl_vat is accurately extracted. "
                "Swiss receipts often use 'CHF' as currency."
            ),
        )

        result = await agent.run(f"Receipt text:\n{raw_text}")
        return result.data
