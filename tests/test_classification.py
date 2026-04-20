from datetime import date

import httpx
import pytest

from bexio_receipts.extraction import ExtractionTrace, classify_accounts
from bexio_receipts.models import Receipt, VatEntry


@pytest.mark.asyncio
async def test_classify_accounts_logic(test_settings, respx_mock):
    """
    Test Step 3 account classification logic using a mocked LLM response.
    """
    test_settings.llm_provider = "ollama"

    # Mock receipt
    receipt = Receipt(
        merchant_name="Prodega",
        transaction_date=date(2026, 1, 31),
        total_incl_vat=214.20,
        vat_breakdown=[
            VatEntry(
                rate=2.6, base_amount=176.70, vat_amount=4.59, total_incl_vat=181.29
            ),
            VatEntry(
                rate=8.1, base_amount=30.45, vat_amount=2.47, total_incl_vat=32.92
            ),
        ],
    )

    raw_text = "Prodega OCR Text with Food and Non-Food items"

    # Mock the LLM response for Step 3
    respx_mock.post(f"{test_settings.ollama_url.rstrip('/')}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1677652288,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"assignments": [{"vat_rate": 2.6, "account_id": "4200", "account_name": "Einkauf Handelsware", "confidence": "high", "reasoning": "Food items"}, {"vat_rate": 8.1, "account_id": "4201", "account_name": "Einkauf Handelsware Non-Food", "confidence": "high", "reasoning": "Non-food items"}]}',
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    trace = ExtractionTrace(ocr_text=raw_text)
    async with httpx.AsyncClient() as client:
        assignments = await classify_accounts(
            receipt, raw_text, test_settings, client, trace
        )

    assert len(assignments) == 2
    assert assignments[0].account_id == "4200"
    assert assignments[1].account_id == "4201"
    assert assignments[0].vat_rate == 2.6
