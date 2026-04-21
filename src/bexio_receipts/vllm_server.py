"""Shared vLLM server lifecycle management."""

import os
import socket
import subprocess
import time
from pathlib import Path

import structlog

from .config import Settings

logger = structlog.get_logger(__name__)

_vllm_process: subprocess.Popen | None = None
_vllm_log_file = None


def is_port_open(host: str, port: int) -> bool:
    """Check if a port is open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def start_vllm_server(
    model: str,
    port: int,
    settings: Settings,
    extra_flags: list[str] | None = None,
    host: str | None = None,
):
    """Start the vLLM server in the background."""
    global _vllm_process  # noqa: PLW0603
    host = host or settings.vision_api_host
    if is_port_open(host, port):
        logger.info("vLLM port already open, skipping startup", port=port)
        return

    cmd = [
        "uv",
        "run",
        "vllm",
        "serve",
        model,
        "--port",
        str(port),
        "--trust-remote-code",
    ]
    if extra_flags:
        cmd.extend(extra_flags)

    logger.info("Starting managed vLLM server", command=" ".join(cmd))
    global _vllm_log_file  # noqa: PLW0603
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)
    _vllm_log_file = open(debug_dir / f"vllm_{port}.log", "ab")

    # Environment variables from user feedback
    env = os.environ.copy()
    env["VLLM_SLEEP_WHEN_IDLE"] = "1"
    env["VLLM_USE_DEEP_GEMM"] = "0"
    env["VLLM_USE_FLASHINFER_MOE_FP16"] = "1"
    env["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
    env["OMP_NUM_THREADS"] = "4"
    env["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"

    _vllm_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=_vllm_log_file,
        env=env,
    )

    # Wait for the server to be ready
    logger.info("Waiting for vLLM server to start...", port=port, timeout=300)
    start_time = time.time()
    while time.time() - start_time < 300:
        if is_port_open(settings.vision_api_host, port):
            logger.info("vLLM server is ready", port=port)
            return
        if _vllm_process.poll() is not None:
            logger.error(
                "vLLM process died unexpectedly", return_code=_vllm_process.returncode
            )
            raise RuntimeError("vLLM server failed to start")
        time.sleep(2)

    logger.error("vLLM server timed out while starting", port=port)
    raise TimeoutError(f"vLLM server didn't start within 300 seconds on port {port}")


def stop_vllm_server():
    """Stop the background vLLM server."""
    global _vllm_process, _vllm_log_file  # noqa: PLW0603
    if _vllm_process:
        try:
            logger.info("Stopping vLLM server")
            _vllm_process.terminate()
            try:
                _vllm_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("vLLM server didn't stop, killing")
                _vllm_process.kill()
        except Exception as e:
            logger.error("Error stopping vLLM process", error=str(e))
        finally:
            _vllm_process = None
            if _vllm_log_file is not None:
                _vllm_log_file.close()
                _vllm_log_file = None
