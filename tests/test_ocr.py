import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bexio_receipts.ocr import async_run_ocr


@pytest.mark.asyncio
async def test_async_run_ocr_success(test_settings):
    """Test successful OCR run using the GLM-OCR SDK singleton."""
    # Mock the PipelineResult
    mock_result = MagicMock()
    mock_result.markdown_result = (
        "| Rate | Amount |\n|------|--------|\n| 8.1% | 100.00 |"
    )
    mock_result.json_result = [
        [
            {"content": "8.1%", "label": "text", "index": 0},
            {"content": "100.00", "label": "text", "index": 1},
        ]
    ]

    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_result

    # Mock get_ocr_parser to return our mock parser
    with patch(
        "bexio_receipts.ocr.get_ocr_parser", return_value=mock_parser
    ) as mock_get:
        markdown, confidence, metadata = await async_run_ocr("test.png", test_settings)

        assert "| 8.1% |" in markdown
        assert confidence == 0.90
        assert len(metadata) == 2
        assert metadata[0]["text"] == "8.1%"

        mock_get.assert_called_once_with(test_settings)
        mock_parser.parse.assert_called_once_with("test.png")


@pytest.mark.asyncio
async def test_async_run_ocr_timeout(test_settings):
    """Test OCR timeout handling."""
    # Setup test_settings with a short timeout
    test_settings.glm_ocr_timeout = 0.01

    import time

    def slow_ocr(*args, **kwargs):
        time.sleep(0.1)
        return "too late", 0.0, []

    # Mock the sync run to be slow
    with patch("bexio_receipts.ocr._sync_run_ocr", side_effect=slow_ocr):
        with pytest.raises(asyncio.TimeoutError):
            await async_run_ocr("test.png", test_settings)


@pytest.mark.asyncio
async def test_async_run_ocr_error(test_settings):
    """Test OCR SDK error propagation."""
    mock_parser = MagicMock()
    mock_parser.parse.side_effect = Exception("SDK Error")

    with patch("bexio_receipts.ocr.get_ocr_parser", return_value=mock_parser):
        with pytest.raises(Exception, match="SDK Error"):
            await async_run_ocr("test.png", test_settings)
