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
                "Extract receipt data from OCR text. "
                "Swiss VAT rates are: 8.1% (standard), 2.6% (reduced), 3.8% (accommodation). "
                "Return null for fields not found. "
                "Use the 'transaction_date' field for the date shown on the receipt. "
                "CRITICAL: If the OCR output is sparse (e.g. just a brand and total), "
                "treat the first line as the 'merchant_name' and prioritize 'total_incl_vat'. "
                "Swiss receipts often use 'CHF' as currency. "
                "If multiple VAT rates are present, breakdown into 'vat_breakdown'. "
                "Ensure merchant name is extracted as cleanly as possible."
            ),
        )

        result = await agent.run(f"Receipt text:\n{raw_text}")
        return result.output
