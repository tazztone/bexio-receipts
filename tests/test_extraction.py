from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bexio_receipts.extraction import extract_receipt
from bexio_receipts.models import Receipt


@pytest.mark.asyncio
async def test_extract_receipt_ollama(test_settings):
    test_settings.llm_provider = "ollama"
    test_settings.llm_model = "test-model"

    # Mocking Agent and result
    mock_result = MagicMock()
    # Pydantic AI now uses .output instead of .data
    mock_result.output = Receipt(
        merchant_name="Mock Coop",
        transaction_date=date(2023, 1, 1),
        total_incl_vat=10.0,
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt = await extract_receipt(
            "Dummy text", test_settings, httpx.AsyncClient()
        )

        assert receipt.merchant_name == "Mock Coop"
        assert receipt.total_incl_vat == 10.0
        mock_agent_instance.run.assert_called_once()


@pytest.mark.asyncio
async def test_extract_receipt_with_vat_breakdown(test_settings):
    test_settings.llm_provider = "ollama"

    from bexio_receipts.models import VatEntry

    mock_result = MagicMock()
    mock_result.output = Receipt(
        merchant_name="Mock Coop",
        transaction_date=date(2023, 1, 1),
        total_incl_vat=110.81,
        vat_breakdown=[
            VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1),
            VatEntry(rate=2.6, base_amount=10.0, vat_amount=0.26),
        ],
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt = await extract_receipt(
            "Dummy text with multiple VATs", test_settings, httpx.AsyncClient()
        )

        assert len(receipt.vat_breakdown) == 2
        assert receipt.vat_breakdown[0].rate == 8.1
        assert receipt.vat_breakdown[1].rate == 2.6
        mock_agent_instance.run.assert_called_once()


def test_receipt_normalization():
    # Test collapse whitespace and preserve case
    r = Receipt(merchant_name="  ALDI   SUISSE  ")
    assert r.merchant_name == "ALDI SUISSE"

    r2 = Receipt(merchant_name="McDonald's")
    assert r2.merchant_name == "McDonald's"

    r3 = Receipt(merchant_name="migrolino")
    assert r3.merchant_name == "migrolino"


def test_receipt_invariants():
    from pydantic import ValidationError

    from bexio_receipts.models import VatEntry

    # Case 1: subtotal + vat != total
    with pytest.raises(ValidationError, match=r"10.0 \+ 2.0 = 12.0 ≠ 15.0"):
        Receipt(subtotal_excl_vat=10.0, vat_amount=2.0, total_incl_vat=15.0)

    # Case 2: vat_breakdown sum != vat_amount
    with pytest.raises(
        ValidationError, match=r"vat_breakdown sum 1.00 ≠ vat_amount 2.00"
    ):
        Receipt(
            vat_amount=2.0,
            vat_breakdown=[VatEntry(rate=8.1, base_amount=10.0, vat_amount=1.0)],
        )

    # Case 3: Success within tolerance
    Receipt(subtotal_excl_vat=10.0, vat_amount=0.81, total_incl_vat=10.81)
