import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bexio_receipts.vllm_server import is_port_open, start_vllm_server, stop_vllm_server


def test_is_port_open():
    with patch("socket.socket") as mock_socket:
        mock_sock_inst = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_inst

        # Open
        mock_sock_inst.connect_ex.return_value = 0
        assert is_port_open("localhost", 8000) is True

        # Closed
        mock_sock_inst.connect_ex.return_value = 1
        assert is_port_open("localhost", 8000) is False

        # Timeout
        mock_sock_inst.connect_ex.side_effect = socket.timeout
        with pytest.raises(socket.timeout):
            is_port_open("localhost", 8000)


@pytest.mark.asyncio
async def test_start_vllm_server_already_running(test_settings):
    with patch("bexio_receipts.vllm_server.is_port_open", return_value=True):
        with patch("subprocess.Popen") as mock_popen:
            await start_vllm_server("model", 8000, test_settings)
            mock_popen.assert_not_called()


@pytest.mark.asyncio
async def test_start_vllm_server_success(test_settings):
    with patch("bexio_receipts.vllm_server.is_port_open") as mock_port:
        # First call False (server not started), second call True (server ready)
        mock_port.side_effect = [False, True]
        with patch("subprocess.Popen") as mock_popen:
            mock_popen_inst = MagicMock()
            mock_popen_inst.poll.return_value = None
            mock_popen.return_value = mock_popen_inst

            with patch("builtins.open", MagicMock()):
                await start_vllm_server(
                    "model", 8000, test_settings, extra_flags=["--test"]
                )
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                assert "--test" in args[0]
                assert "VLLM_SLEEP_WHEN_IDLE" in kwargs["env"]


def test_stop_vllm_server_success():
    mock_process = MagicMock()
    mock_log = MagicMock()

    with patch("bexio_receipts.vllm_server._vllm_process", mock_process):
        with patch("bexio_receipts.vllm_server._vllm_log_file", mock_log):
            stop_vllm_server()
            mock_process.terminate.assert_called_once()
            mock_process.wait.assert_called_once()
            mock_log.close.assert_called_once()


def test_stop_vllm_server_kill():
    mock_process = MagicMock()
    mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

    with patch("bexio_receipts.vllm_server._vllm_process", mock_process):
        stop_vllm_server()
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
