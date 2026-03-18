from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from .models import Receipt
from .config import Settings
import logging

logger = logging.getLogger(__name__)

async def extract_receipt(raw_text: str, settings: Settings) -> Receipt:
    """
    Extract receipt data from OCR text using Pydantic AI.
    """
    if settings.llm_provider == "ollama":
        model = OpenAIChatModel(
            model_name=settings.llm_model,
            provider=OllamaProvider(base_url="http://localhost:11434/v1"),
        )
    elif settings.llm_provider == "openai":
        # Assumes OPENAI_API_KEY is set in environment
        model = OpenAIChatModel(model_name=settings.llm_model)
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")

    agent = Agent(
        model,
        result_type=Receipt,
        system_prompt=(
            "Extract receipt data from OCR text. Swiss VAT rates are: "
            "8.1% (standard), 2.6% (reduced — food, books), 3.8% (accommodation). "
            "Return null for fields not found. If multiple VAT rates appear, use the dominant one. "
            "Ensure the total_incl_vat is accurately extracted. "
            "Swiss receipts often use 'CHF' as currency."
        ),
    )

    result = await agent.run(f"Receipt text:\n{raw_text}")
    return result.data
