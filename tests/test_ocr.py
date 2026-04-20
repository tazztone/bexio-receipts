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

@patch("bexio_receipts.ocr.socket.socket")
def test_is_port_open(mock_socket):
    from bexio_receipts.ocr import _is_port_open

    # Mock open port
    mock_instance = MagicMock()
    mock_instance.connect_ex.return_value = 0
    mock_socket.return_value.__enter__.return_value = mock_instance
    assert _is_port_open("localhost", 8000) is True

    # Mock closed port
    mock_instance.connect_ex.return_value = 1
    assert _is_port_open("localhost", 8000) is False

@patch("bexio_receipts.ocr._is_port_open")
@patch("bexio_receipts.ocr.subprocess.Popen")
def test_start_vllm_server(mock_popen, mock_is_port_open, test_settings):
    from bexio_receipts.ocr import _start_vllm_server

    # Port is open - should not start server
    mock_is_port_open.return_value = True
    _start_vllm_server(test_settings)
    mock_popen.assert_not_called()

    # Port is closed - should start server
    mock_is_port_open.return_value = False
    with patch("bexio_receipts.ocr.time.sleep"):  # avoid waiting in test
        _start_vllm_server(test_settings)
    mock_popen.assert_called_once()

@patch("bexio_receipts.ocr.GlmOcr")
@patch("bexio_receipts.ocr._start_vllm_server")
def test_get_ocr_parser(mock_start, mock_glmocr, test_settings):
    import bexio_receipts.ocr as ocr_module

    # Ensure clean state
    ocr_module._ocr_parser = None

    test_settings.glm_ocr_manage_server = True
    parser = ocr_module.get_ocr_parser(test_settings)

    mock_start.assert_called_once_with(test_settings)
    mock_glmocr.assert_called_once()
    assert parser is not None
    assert parser == ocr_module._ocr_parser

    # Second call should return singleton without re-init
    mock_start.reset_mock()
    mock_glmocr.reset_mock()
    parser2 = ocr_module.get_ocr_parser(test_settings)
    assert parser2 is parser
    mock_start.assert_not_called()
    mock_glmocr.assert_not_called()

def test_close_ocr_parser():
    import subprocess

    import bexio_receipts.ocr as ocr_module

    # Mock active parser and vllm process
    mock_parser = MagicMock()
    mock_vllm = MagicMock()

    ocr_module._ocr_parser = mock_parser
    ocr_module._vllm_process = mock_vllm

    ocr_module.close_ocr_parser()

    mock_parser.__exit__.assert_called_once_with(None, None, None)
    mock_vllm.terminate.assert_called_once()
    mock_vllm.wait.assert_called_once()

    assert ocr_module._ocr_parser is None
    assert ocr_module._vllm_process is None

    # Test TimeoutExpired
    ocr_module._vllm_process = mock_vllm
    mock_vllm.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
    ocr_module.close_ocr_parser()
    mock_vllm.kill.assert_called_once()
