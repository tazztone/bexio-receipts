import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bexio_receipts.ocr import async_run_ocr


@pytest.mark.asyncio
async def test_async_run_ocr_success(test_settings):
    """Test successful OCR run using the GLM-OCR SDK."""
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

    # Mock GlmOcr context manager
    with patch("bexio_receipts.ocr.GlmOcr") as MockGlmOcr:
        mock_instance = MockGlmOcr.return_value.__enter__.return_value
        mock_instance.parse.return_value = mock_result

        markdown, confidence, metadata = await async_run_ocr("test.png", test_settings)

        assert "| 8.1% |" in markdown
        assert confidence == 0.90
        assert len(metadata) == 2
        assert metadata[0]["text"] == "8.1%"

        # Verify GlmOcr was called with correct parameters
        MockGlmOcr.assert_called_once_with(
            mode="selfhosted",
            ocr_api_host=test_settings.glm_ocr_api_host,
            ocr_api_port=test_settings.glm_ocr_api_port,
            layout_device=test_settings.glm_ocr_layout_device,
            log_level="WARNING",
        )
        mock_instance.parse.assert_called_once_with("test.png")


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
    with patch("bexio_receipts.ocr.GlmOcr") as MockGlmOcr:
        mock_instance = MockGlmOcr.return_value.__enter__.return_value
        mock_instance.parse.side_effect = Exception("SDK Error")

        with pytest.raises(Exception, match="SDK Error"):
            await async_run_ocr("test.png", test_settings)
