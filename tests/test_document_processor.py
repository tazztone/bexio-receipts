from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bexio_receipts.document_processor import (
    OcrProcessor,
    VisionProcessor,
    extract_json_block,
)
from bexio_receipts.extraction import ExtractionTrace
from bexio_receipts.models import Receipt, VatEntry


def test_extract_json_block_valid():
    # Markdown json block
    assert extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    # Markdown block without language
    assert extract_json_block('```\n{"b": 2}\n```') == {"b": 2}
    # Fallback to brace search
    assert extract_json_block('some text\n{"c": 3}\nmore text') == {"c": 3}
    # Empty block
    assert extract_json_block("   ") is None


def test_extract_json_block_error_path():
    # Malformed json in markdown block
    assert extract_json_block('```json\n{"a": 1\n```') is None
    # Invalid json directly
    assert extract_json_block('{"b": 2') is None
    # valid JSON with array but we are mostly testing decode error
    assert extract_json_block('```\n[1, 2\n```') is None
    # No json braces and no markdown
    assert extract_json_block('just some random text') is None


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
            assert "PDF Corp" in result.raw_text
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

        with (
            patch.object(VisionProcessor, "_encode_image", return_value="base64"),
            pytest.raises(ValueError, match="Failed to parse VLM output"),
        ):
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


def test_extract_json_block_valid_json():
    text = '{"key": "value", "number": 42}'
    result = extract_json_block(text)
    assert result == {"key": "value", "number": 42}


def test_extract_json_block_markdown_json():
    text = '''Here is the extracted data:
```json
{"merchant_name": "Test", "total": 100.0}
```
Some extra text.'''
    result = extract_json_block(text)
    assert result == {"merchant_name": "Test", "total": 100.0}


def test_extract_json_block_markdown_generic():
    text = '''```
{"field": "test"}
```'''
    result = extract_json_block(text)
    assert result == {"field": "test"}


def test_extract_json_block_fallback_braces():
    text = '''Some garbage before {"found": true} and some garbage after.'''
    result = extract_json_block(text)
    assert result == {"found": True}


def test_extract_json_block_empty():
    assert extract_json_block("") is None
    assert extract_json_block("   \n  ") is None


def test_extract_json_block_malformed_json():
    text = '```json\n{"missing_quote: true}\n```'
    assert extract_json_block(text) is None


def test_extract_json_block_no_braces():
    text = "Just some plain text without any JSON."
    assert extract_json_block(text) is None
