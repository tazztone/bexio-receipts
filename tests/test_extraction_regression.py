import httpx
import pytest

from bexio_receipts.extraction import extract_receipt


@pytest.fixture
def prodega_ocr_text():
    return "Dummy Prodega OCR text for regression testing. Content irrelevant due to LLM mock."


@pytest.mark.asyncio
async def test_prodega_extraction_logic(test_settings, prodega_ocr_text, respx_mock):
    """
    Regression test for Prodega receipt extraction.
    Uses respx to mock the Ollama HTTP responses for the two-step agent pipeline.
    Step 1 (Searcher) returns IntermediateReceipt with a vat_table_raw Markdown snippet.
    Step 2 (VAT Parser) returns list[RawVatRow] extracted from that snippet.
    """
    test_settings.llm_provider = "ollama"

    # Step 1 response: IntermediateReceipt with Markdown VAT table
    step1_response = {
        "id": "chatcmpl-step1",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"merchant_name": "Prodega", "transaction_date": "31.01.2026", '
                        '"currency": "CHF", "total_incl_vat": 214.20, '
                        '"vat_table_raw": "| MwSt | MwSt-Betrag | Netto | Brutto |\\n'
                        "|------|-------------|-------|--------|\\n"
                        "| 2.6% | 4.59 | 176.70 | 181.29 |\\n"
                        '| 8.1% | 2.47 | 30.45 | 32.92 |", '
                        '"payment_method": "cash"}'
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
    }

    # Step 2 response: list[RawVatRow]
    step2_response = {
        "id": "chatcmpl-step2",
        "object": "chat.completion",
        "created": 1677652290,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"rows": [{"rate": 2.6, "col_a": 4.59, "col_b": 176.70, "col_c": 181.29}, '
                        '{"rate": 8.1, "col_a": 2.47, "col_b": 30.45, "col_c": 32.92}]}'
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
    }

    # Mock both sequential LLM calls
    responses = [
        httpx.Response(200, json=step1_response),
        httpx.Response(200, json=step2_response),
    ]

    def side_effect(request):
        return responses.pop(0)

    respx_mock.post(f"{test_settings.ollama_url.rstrip('/')}/v1/chat/completions").mock(
        side_effect=side_effect
    )

    async with httpx.AsyncClient() as client:
        receipt, _ = await extract_receipt(prodega_ocr_text, test_settings, client)

    # Assertions using pytest.approx for floating point safety
    assert receipt.merchant_name == "Prodega"
    assert receipt.total_incl_vat == pytest.approx(214.20, abs=0.01)
    assert len(receipt.vat_breakdown) == 2

    vat_2_6 = next(v for v in receipt.vat_breakdown if abs(v.rate - 2.6) < 0.01)
    vat_8_1 = next(v for v in receipt.vat_breakdown if abs(v.rate - 8.1) < 0.01)

    assert vat_2_6.vat_amount == pytest.approx(4.59, abs=0.01)
    assert vat_8_1.vat_amount == pytest.approx(2.47, abs=0.01)
    assert round(vat_2_6.vat_amount + vat_8_1.vat_amount, 2) == pytest.approx(
        7.06, abs=0.01
    )
