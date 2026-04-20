from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bexio_receipts.extraction import extract_receipt, resolve_vat_rows
from bexio_receipts.models import RawReceipt, RawVatRow, Receipt


@pytest.mark.asyncio
async def test_extract_receipt_ollama(test_settings):
    test_settings.llm_provider = "ollama"
    test_settings.llm_model = "test-model"
    test_settings.env = "production"

    # Mocking Agent and result
    mock_result = MagicMock()

    # Pydantic AI now uses .output instead of .data
    mock_result.output = RawReceipt(
        merchant_name="Mock Coop",
        transaction_date="2023-01-01",
        total_incl_vat=10.81,
        vat_rows=[RawVatRow(rate=8.1, col_a=0.81, col_b=10.0, col_c=10.81)],
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt, _ = await extract_receipt(
            "Dummy text", test_settings, httpx.AsyncClient()
        )

        assert receipt.merchant_name == "Mock Coop"
        assert receipt.total_incl_vat == 10.81
        mock_agent_instance.run.assert_called_once()


@pytest.mark.asyncio
async def test_extract_receipt_with_vat_breakdown(test_settings):
    pass


@pytest.mark.asyncio
async def test_extract_receipt_fallback(test_settings):
    test_settings.llm_provider = "openrouter"
    test_settings.openrouter_api_key = "dummy"
    test_settings.openrouter_use_structured_output = False

    mock_result = MagicMock()
    # Pydantic AI now uses .output instead of .data
    mock_result.output = (
        '```json\n{"merchant_name": "Fallback", "transaction_date": "2023-01-01"}\n```'
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt, _ = await extract_receipt(
            "Dummy text", test_settings, httpx.AsyncClient()
        )

        assert receipt.merchant_name == "Fallback"


@pytest.mark.asyncio
async def test_extract_receipt_openrouter_missing_key(test_settings):
    test_settings.llm_provider = "openrouter"
    test_settings.openrouter_api_key = None
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        await extract_receipt("Dummy text", test_settings, httpx.AsyncClient())


@pytest.mark.asyncio
async def test_extract_receipt_openai(test_settings):
    test_settings.llm_provider = "openai"
    test_settings.openai_api_key = "dummy_key"
    import os

    os.environ["OPENAI_API_KEY"] = "dummy_key"

    mock_result = MagicMock()

    mock_result.output = RawReceipt(
        merchant_name="Mock Coop",
        transaction_date="2023-01-01",
        total_incl_vat=10.81,
        vat_rows=[RawVatRow(rate=8.1, col_a=0.81, col_b=10.0, col_c=10.81)],
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt, _ = await extract_receipt(
            "Dummy text", test_settings, httpx.AsyncClient()
        )

        assert receipt.merchant_name == "Mock Coop"
        assert receipt.total_incl_vat == 10.81

    mock_result = MagicMock()
    mock_result.output = RawReceipt(
        merchant_name="Mock Coop",
        transaction_date="2023-01-01",
        total_incl_vat=118.36,
        vat_rows=[
            RawVatRow(rate=8.1, col_a=100.0, col_b=8.1, col_c=108.1),
            RawVatRow(rate=2.6, col_a=10.0, col_b=0.26, col_c=10.26),
        ],
    )

    with patch("bexio_receipts.extraction.Agent") as mock_agent_class:
        mock_agent_instance = mock_agent_class.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        receipt, _ = await extract_receipt(
            "Dummy text with multiple VATs", test_settings, httpx.AsyncClient()
        )

        assert len(receipt.vat_breakdown) == 2
        assert receipt.vat_breakdown[0].rate == 8.1
        assert receipt.vat_breakdown[1].rate == 2.6
        mock_agent_instance.run.assert_called_once()


def test_resolve_vat_rows_strategy_1():
    """Test Strategy 1: Rate | VAT | Base (Prodega pattern)"""
    rows = [
        # Rate=2.6, col_a=2.6 (matches rate), col_b=4.59 (vat), col_c=176.70 (base)
        RawVatRow(rate=2.6, col_a=2.6, col_b=4.59, col_c=176.70),
        # Rate=8.1, col_a=8.1 (matches rate), col_b=2.47 (vat), col_c=30.45 (base)
        RawVatRow(rate=8.1, col_a=8.1, col_b=2.47, col_c=30.45),
    ]
    entries = resolve_vat_rows(rows)
    assert len(entries) == 2
    assert entries[0].rate == 2.6
    assert entries[0].vat_amount == 4.59
    assert entries[0].base_amount == 176.70
    assert entries[1].rate == 8.1
    assert entries[1].vat_amount == 2.47
    assert entries[1].base_amount == 30.45


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
