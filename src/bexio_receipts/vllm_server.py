"""Shared vLLM server lifecycle management."""

import asyncio
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import structlog

from .config import Settings

logger = structlog.get_logger(__name__)

VLLM_PID_FILE = Path("debug/vllm.pid")
_vllm_process: subprocess.Popen | None = None
_vllm_log_file = None
_vllm_lock: asyncio.Lock | None = None


def build_vllm_flags(settings: Settings) -> list[str]:
    """Build vLLM command line flags from settings."""
    flags = [
        "--max-model-len",
        str(settings.vision_max_model_len),
        "--gpu-memory-utilization",
        str(settings.vision_gpu_memory_utilization),
        "--max-num-seqs",
        str(settings.vision_max_num_seqs),
        "--tensor-parallel-size",
        str(settings.vision_tensor_parallel_size),
        "--served-model-name",
        settings.vision_served_name,
        "--default-chat-template-kwargs",
        '{"enable_thinking": false}',
    ]

    if settings.vision_quantization and settings.vision_quantization != "auto":
        flags.extend(["--quantization", settings.vision_quantization])

    if (
        settings.vision_reasoning_parser
        and settings.vision_reasoning_parser.lower() != "none"
    ):
        flags.extend([
            "--reasoning-parser",
            settings.vision_reasoning_parser,
        ])

    if (
        settings.vision_speculative_config
        and settings.vision_speculative_config.lower() != "none"
    ):
        flags.extend([
            "--speculative-config",
            settings.vision_speculative_config,
        ])

    if settings.vision_enable_expert_parallel:
        flags.append("--enable-expert-parallel")

    return flags


def is_port_open(host: str, port: int) -> bool:
    """Check if a port is open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


async def start_vllm_server(
    model: str,
    port: int,
    settings: Settings,
    extra_flags: list[str] | None = None,
    host: str | None = None,
):
    """Start the vLLM server in the background (Async)."""
    global _vllm_process, _vllm_log_file, _vllm_lock  # noqa: PLW0603
    if _vllm_lock is None:
        _vllm_lock = asyncio.Lock()

    async with _vllm_lock:
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
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)

        # Open log file with error handling to avoid handle leaks
        log_path = debug_dir / f"vllm_{port}.log"
        _vllm_log_file = open(log_path, "ab")  # noqa: SIM115

        try:
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
            # Record PID for cross-session management
            VLLM_PID_FILE.write_text(str(_vllm_process.pid))
        except Exception as e:
            logger.error("Failed to spawn vLLM process", error=str(e))
            if _vllm_log_file:
                _vllm_log_file.close()
                _vllm_log_file = None
            raise

        # Wait for the server to be ready without blocking the loop
        logger.info("Waiting for vLLM server to start...", port=port, timeout=300)
        start_time = time.time()
        last_pos = 0
        while time.time() - start_time < 300:
            # Stream logs from the file
            try:
                if log_path.exists():
                    with open(log_path, errors="replace") as f:
                        f.seek(last_pos)
                        new_content = f.read()
                        if new_content:
                            print(new_content, end="", flush=True)  # noqa: T201
                            last_pos = f.tell()
            except Exception:
                # Don't let log streaming crash the startup
                pass

            if is_port_open(host, port):
                logger.info("vLLM server is ready", port=port)
                # Small grace period for actual API readiness
                await asyncio.sleep(2)
                return
            if _vllm_process.poll() is not None:
                logger.error(
                    "vLLM process died unexpectedly",
                    return_code=_vllm_process.returncode,
                )
                if _vllm_log_file:
                    _vllm_log_file.close()
                    _vllm_log_file = None
                raise RuntimeError("vLLM server failed to start")
            await asyncio.sleep(2)

        logger.error("vLLM server timed out while starting", port=port)
        raise TimeoutError(
            f"vLLM server didn't start within 300 seconds on port {port}"
        )


def terminate_managed_vllm() -> tuple[bool, str]:
    """Terminate the managed vLLM server across sessions."""
    if not VLLM_PID_FILE.exists():
        return False, "No managed vLLM server found (PID file missing)."

    try:
        pid = int(VLLM_PID_FILE.read_text().strip())
    except Exception as e:
        VLLM_PID_FILE.unlink(missing_ok=True)
        return (
            False,
            f"Failed to read PID file, it might be corrupt. Cleaned up. Error: {e}",
        )

    try:
        # Check if process exists
        os.kill(pid, 0)
    except OSError:
        VLLM_PID_FILE.unlink(missing_ok=True)
        return False, f"Process {pid} is not running. Cleaned up PID file."

    try:
        logger.info("Terminating vLLM server", pid=pid)
        os.kill(pid, signal.SIGTERM)

        # Wait for it to die
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(1)
            except OSError:
                # Process is dead
                break
        else:
            logger.warning(
                "vLLM server didn't stop with SIGTERM, killing with SIGKILL", pid=pid
            )
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)

    except Exception as e:
        return False, f"Error terminating process {pid}: {e}"
    finally:
        VLLM_PID_FILE.unlink(missing_ok=True)

    return True, f"Successfully stopped vLLM server (PID {pid})."


def stop_vllm_server():
    """Stop the background vLLM server (in-session wrapper)."""
    global _vllm_process, _vllm_log_file  # noqa: PLW0603

    success, message = terminate_managed_vllm()
    if success:
        logger.info(message)
    else:
        logger.debug(message)

    _vllm_process = None
    if _vllm_log_file is not None:
        _vllm_log_file.close()
        _vllm_log_file = None
