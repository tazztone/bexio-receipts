import signal
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bexio_receipts.vllm_server import (
    build_vllm_flags,
    is_port_open,
    start_vllm_server,
    stop_vllm_server,
    terminate_managed_vllm,
)


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
    with (
        patch("bexio_receipts.vllm_server.is_port_open", return_value=True),
        patch("subprocess.Popen") as mock_popen,
    ):
        await start_vllm_server("model", 8000, test_settings)
        mock_popen.assert_not_called()


@pytest.mark.asyncio
async def test_start_vllm_server_success(test_settings):
    with patch("bexio_receipts.vllm_server.is_port_open") as mock_port:
        # First call False (server not started), second call True (server ready)
        mock_port.side_effect = [False, True]
        mock_pid_file = MagicMock(spec=Path)
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("bexio_receipts.vllm_server.VLLM_PID_FILE", mock_pid_file),
            patch("builtins.print"),  # Suppress prints from log tailing
        ):
            mock_popen_inst = MagicMock()
            mock_popen_inst.poll.return_value = None
            mock_popen_inst.pid = 1234
            mock_popen.return_value = mock_popen_inst

            with patch("builtins.open", MagicMock()):
                await start_vllm_server(
                    "model", 8000, test_settings, extra_flags=["--test"]
                )
                mock_popen.assert_called_once()
                mock_pid_file.write_text.assert_called_once_with("1234")
                args, kwargs = mock_popen.call_args
                assert "--test" in args[0]
                assert "VLLM_SLEEP_WHEN_IDLE" in kwargs["env"]


def test_terminate_managed_vllm_no_file():
    mock_pid_file = MagicMock(spec=Path)
    mock_pid_file.exists.return_value = False
    with patch("bexio_receipts.vllm_server.VLLM_PID_FILE", mock_pid_file):
        success, message = terminate_managed_vllm()
        assert success is False
        assert "No managed vLLM server found" in message


def test_terminate_managed_vllm_success():
    mock_pid_file = MagicMock(spec=Path)
    mock_pid_file.exists.return_value = True
    mock_pid_file.read_text.return_value = "1234"
    with (
        patch("bexio_receipts.vllm_server.VLLM_PID_FILE", mock_pid_file),
        patch("os.kill") as mock_kill,
        patch("time.sleep"),
    ):
        # First call to os.kill(pid, 0) succeeds (process exists)
        # Second call to os.kill(pid, 0) fails (process gone after SIGTERM)
        mock_kill.side_effect = [None, None, OSError()]

        success, message = terminate_managed_vllm()

        assert success is True
        assert "Successfully stopped vLLM server" in message
        mock_kill.assert_any_call(1234, 0)
        mock_kill.assert_any_call(1234, signal.SIGTERM)
        mock_pid_file.unlink.assert_called_once()


def test_stop_vllm_server_success():
    mock_log = MagicMock()

    with (
        patch(
            "bexio_receipts.vllm_server.terminate_managed_vllm",
            return_value=(True, "Success"),
        ),
        patch("bexio_receipts.vllm_server._vllm_log_file", mock_log),
    ):
        stop_vllm_server()
        mock_log.close.assert_called_once()


def test_build_vllm_flags_gguf(test_settings):
    test_settings.vision_quantization = "gguf"
    flags = build_vllm_flags(test_settings)
    assert "--quantization" in flags
    assert flags[flags.index("--quantization") + 1] == "gguf"
