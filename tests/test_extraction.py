import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bexio_receipts.extraction import extract_receipt
from bexio_receipts.models import Receipt
from datetime import date


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

        receipt = await extract_receipt("Dummy text", test_settings)

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

        receipt = await extract_receipt("Dummy text with multiple VATs", test_settings)

        assert len(receipt.vat_breakdown) == 2
        assert receipt.vat_breakdown[0].rate == 8.1
        assert receipt.vat_breakdown[1].rate == 2.6
        mock_agent_instance.run.assert_called_once()
