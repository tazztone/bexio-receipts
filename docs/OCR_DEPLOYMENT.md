# GLM-OCR Deployment Guide

This guide covers the deployment of the GLM-OCR backend, which is the recommended setup for production processing in `bexio-receipts`.

## 🏗️ Architecture

The OCR pipeline consists of two stages:
1.  **Layout Analysis**: Performed locally by the `bexio-receipts` process using PP-DocLayoutV3.
2.  **OCR Inference**: Performed by a **vLLM** server running the `zai-org/GLM-OCR` model.

## 🚀 Managed Deployment (Recommended)

`bexio-receipts` includes built-in lifecycle management for the OCR server. It will automatically start and stop the vLLM server as needed.

### 1. Prerequisites
- NVIDIA GPU with at least 8GB VRAM (RTX 3060 or higher).
- CUDA drivers and toolkit installed.
- `vllm` package installed in the environment (`uv add vllm`).

### 2. Configuration
Ensure your `.env` contains the management flags:

```ini
GLM_OCR_MANAGE_SERVER=true
GLM_OCR_VLLM_GPU_MEMORY_UTILIZATION=0.2  # Adjust based on your VRAM
GLM_OCR_VLLM_MAX_NUM_SEQS=1              # Keeps VRAM usage low
GLM_OCR_VLLM_MAX_MODEL_LEN=8192          # Model context limit
GLM_OCR_MAX_TOKENS=4096                  # SDK output limit (leave room for prompt)
```

### 3. Usage
Simply start the application:
```bash
uv run bexio-receipts start
```
The app will detect if port 8080 is closed, launch vLLM in the background, and wait for it to be ready before processing receipts.

---

## 🛠️ Manual Deployment (Optional)

If you prefer to run the OCR server as a separate service (e.g., via `systemd` or Docker), set `GLM_OCR_MANAGE_SERVER=false` and launch it manually:

```bash
uv run vllm serve zai-org/GLM-OCR \
  --port 8080 \
  --max-model-len 8192 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.2 \
  --served-model-name glm-ocr \
  --trust-remote-code \
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'
```

## ⚙️ Settings Reference

| Variable | Default | Description |
|---|---|---|
| `GLM_OCR_TIMEOUT` | 300 | Total budget for the entire OCR stage (seconds). |
| `GLM_OCR_CONNECT_TIMEOUT` | 120 | Wait time for vLLM to warm up. |
| `GLM_OCR_REQUEST_TIMEOUT` | 180 | Budget for a single image inference. |
| `GLM_OCR_MAX_TOKENS` | 4096 | Maximum tokens the SDK will request from vLLM. |

## 🛠️ Troubleshooting

### "BadRequestError: This model's maximum context length is 8192"
This happens if `GLM_OCR_MAX_TOKENS` is too high. Ensure it is significantly lower than `GLM_OCR_VLLM_MAX_MODEL_LEN` (e.g., 4096 vs 8192) to leave room for the image input.

### Out of Memory (OOM)
If the server fails to start, reduce `GLM_OCR_VLLM_GPU_MEMORY_UTILIZATION` (e.g., to `0.15`) or ensure no other processes are using the GPU.

## 📚 Reference
- Official Repository: [zai-org/GLM-OCR](https://github.com/zai-org/GLM-OCR)
- Technical Report: [arXiv:2603.10910](https://arxiv.org/abs/2603.10910)
