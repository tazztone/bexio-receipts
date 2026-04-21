import asyncio
from unittest.mock import MagicMock, patch

import pytest

import bexio_receipts.ocr
import bexio_receipts.vllm_server
from bexio_receipts.ocr import (
    async_run_ocr,
    close_ocr_parser,
    get_ocr_parser,
)
from bexio_receipts.vllm_server import is_port_open


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


def test_is_port_open():
    with patch("socket.socket") as mock_socket:
        mock_sock_inst = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_inst
        mock_sock_inst.connect_ex.return_value = 0
        assert is_port_open("localhost", 1234)

        mock_sock_inst.connect_ex.return_value = 1
        assert not is_port_open("localhost", 1234)


def test_get_ocr_parser(test_settings):
    # reset global state
    bexio_receipts.ocr._ocr_parser = None
    bexio_receipts.vllm_server._vllm_process = None

    test_settings.glm_ocr_manage_server = True
    test_settings.glm_ocr_api_host = "localhost"
    test_settings.glm_ocr_api_port = 1234

    with (
        patch("bexio_receipts.ocr.start_vllm_server") as mock_start,
        patch("time.sleep"),
        patch("bexio_receipts.ocr.GlmOcr") as mock_glm,
    ):
        mock_glm_inst = MagicMock()
        mock_glm.return_value = mock_glm_inst

        parser = get_ocr_parser(test_settings)
        assert parser is mock_glm_inst
        mock_glm_inst.__enter__.assert_called_once()
        mock_start.assert_called_once()

    # close parser
    with patch("bexio_receipts.ocr.stop_vllm_server") as mock_stop:
        close_ocr_parser()

        assert bexio_receipts.ocr._ocr_parser is None
        mock_glm_inst.__exit__.assert_called_once()
        mock_stop.assert_called_once()


def test_close_ocr_parser_exceptions(test_settings):
    bexio_receipts.ocr._ocr_parser = MagicMock()
    bexio_receipts.ocr._ocr_parser.__exit__.side_effect = Exception("test exit error")

    bexio_receipts.vllm_server._vllm_process = MagicMock()
    import subprocess

    bexio_receipts.vllm_server._vllm_process.wait.side_effect = (
        subprocess.TimeoutExpired(cmd="", timeout=5)
    )

    with patch("bexio_receipts.ocr.stop_vllm_server"):
        close_ocr_parser()

    assert bexio_receipts.ocr._ocr_parser is None


def test_sync_run_ocr_fallback_metadata(test_settings):
    from bexio_receipts.ocr import _sync_run_ocr

    mock_result = MagicMock()
    mock_result.markdown_result = "fallback markdown"
    mock_result.json_result = []

    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_result

    with patch("bexio_receipts.ocr.get_ocr_parser", return_value=mock_parser):
        markdown, _conf, meta = _sync_run_ocr("test.png", test_settings)
        assert markdown == "fallback markdown"
        assert len(meta) == 1
        assert meta[0]["text"] == "fallback markdown"
