# API Reference

The Review Dashboard is built with FastAPI and provides several endpoints for integration and monitoring.

## 📋 Automatic Documentation
FastAPI provides interactive API documentation out-of-the-box:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

> Note: Accessing these endpoints requires the same credentials as the dashboard (`REVIEW_USERNAME`/`REVIEW_PASSWORD`).

## 📊 Monitoring & Health

### `GET /healthz`
Returns a JSON object indicating the health of core dependencies (Database, bexio API, Ingestion sources).

**Example Response:**
```json
{
  "status": "ok",
  "db": "ok",
  "bexio": "ok",
  "imap": "configured",
  "gdrive": "not_configured"
}
```

### `GET /metrics`
Returns Prometheus-compatible metrics.
- `receipts_processed_total`: Total receipts successfully booked.
- `receipts_failed_total`: Number of items currently in the review queue.
- `ocr_confidence_avg`: Average confidence score from the OCR engine.

### `GET /stats`
Returns an HTML fragment (or page) with high-level processing statistics.

## 🧾 Review Queue (Dashboard)

### `GET /`
Main dashboard listing receipts awaiting manual review. Supports pagination (`page`) and searching (`search`).

### `GET /review/{review_id}`
Returns the review form for a specific receipt.

### `POST /push/{review_id}`
Books the receipt in bexio with the provided form data.

### `POST /discard/{review_id}`
Removes the receipt from the review queue without booking it.

### `POST /bulk-action`
Performs actions (`process` or `discard`) on multiple IDs at once.

## 🖼️ Assets

### `GET /image/{review_id}`
Serves the original receipt image (PNG/JPG/PDF).

### `GET /thumbnail/{review_id}`
Serves a low-resolution JPEG thumbnail for gallery views.

## ⚙️ Setup & Hardware

### `GET /setup`
The interactive setup wizard for verifying local models and hardware compatibility.

### `POST /setup/pull-model`
Triggers an Ollama model pull for the configured OCR or LLM engine.
