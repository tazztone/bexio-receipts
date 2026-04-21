from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bexio_receipts.document_processor import (
    OcrProcessor,
    VisionProcessor,
)
from bexio_receipts.extraction import ExtractionTrace
from bexio_receipts.models import Receipt, VatEntry


@pytest.fixture
def vision_processor():
    return VisionProcessor()


@pytest.fixture
def ocr_processor():
    return OcrProcessor()


@pytest.mark.asyncio
async def test_vision_processor_process_pdf(vision_processor, test_settings, tmp_path):
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_text("dummy pdf")

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"merchant_name": "PDF Corp", "transaction_date": "2026-01-01", "total_incl_vat": 123.45, "currency": "CHF", "vat_rows": [], "account_assignments": [], "confidence": 0.99}'
            )
        )
    ]

    with patch("bexio_receipts.document_processor.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.close = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(
            VisionProcessor, "_render_pdf_to_images", return_value=["base64data"]
        ):
            result = await vision_processor.process(str(pdf_file), test_settings)

            assert result.merchant_name == "PDF Corp"
            assert result.total_incl_vat == 123.45
            assert "Vision extraction from" in result.raw_text
            mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_vision_processor_process_image(
    vision_processor, test_settings, tmp_path
):
    img_file = tmp_path / "test.png"
    img_file.write_text("dummy img")

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"merchant_name": "Img Shop", "transaction_date": "2026-02-02", "total_incl_vat": 45.60, "currency": "CHF", "vat_rows": [], "account_assignments": [], "confidence": 0.92}'
            )
        )
    ]

    with patch("bexio_receipts.document_processor.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.close = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(VisionProcessor, "_encode_image", return_value="base64data"):
            result = await vision_processor.process(str(img_file), test_settings)

            assert result.merchant_name == "Img Shop"
            assert result.total_incl_vat == 45.60
            mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_vision_processor_parsing_error(
    vision_processor, test_settings, tmp_path
):
    img_file = tmp_path / "test.png"
    img_file.touch()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="invalid json"))]

    with patch("bexio_receipts.document_processor.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.close = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(VisionProcessor, "_encode_image", return_value="base64"):
            with pytest.raises(ValueError, match="Failed to parse VLM output"):
                await vision_processor.process(str(img_file), test_settings)


@pytest.mark.asyncio
async def test_ocr_processor_process(ocr_processor, test_settings, tmp_path):
    img_file = tmp_path / "test.png"
    img_file.touch()

    receipt = Receipt(
        merchant_name="OCR Shop",
        transaction_date=date(2026, 3, 3),
        total_incl_vat=75.0,
        currency="CHF",
        vat_breakdown=[VatEntry(rate=8.1, base_amount=69.38, vat_amount=5.62)],
    )
    trace = ExtractionTrace(ocr_text="ocr raw")

    with (
        patch(
            "bexio_receipts.document_processor.async_run_ocr",
            return_value=("ocr raw", 0.99, []),
        ),
        patch(
            "bexio_receipts.document_processor.extract_receipt",
            return_value=(receipt, trace),
        ),
        patch("bexio_receipts.document_processor.classify_accounts", return_value=[]),
    ):
        result = await ocr_processor.process(str(img_file), test_settings)

        assert result.merchant_name == "OCR Shop"
        assert result.confidence == 0.99
        assert result.vat_rows[0].rate == 8.1
