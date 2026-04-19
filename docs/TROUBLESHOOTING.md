# Troubleshooting Guide

## Common Errors & Fixes

### 1. `Ollama Connection Error`
**Symptoms**: `httpx.ConnectError` or 500 errors during extraction.
**Fix**: 
- Ensure Ollama is running: `ollama list`.
- Verify `OLLAMA_URL` in your `.env`.
- If running in Docker, use `host.docker.internal` or the actual IP of the host machine.

### 2. `PaddleOCR: libpoppler-cpp-dev not found`
**Symptoms**: Import errors or "Command not found" when processing PDFs.
**Fix**: 
- **Linux**: `sudo apt-get install libpoppler-cpp-dev`
- **macOS**: `brew install poppler`

### 3. `bexio 401 Unauthorized`
**Symptoms**: Receipt extraction works, but pushing to bexio fails with 401.
**Fix**: 
- Your PAT (Personal Access Token) is expired or invalid.
- Ensure the token has `expense_show`, `expense_create`, and `file_show` permissions.

### 4. `Security: Password rejected`
**Symptoms**: Application fails to start with `ValueError: review_password must be changed...`.
**Fix**: 
- If `ENV=production`, the validator ensures you have changed the default password.
- **Note**: The validator specifically checks for the literal string `password`. You should always set a strong, unique password regardless of whether the validator catches it.

### 5. `Total/Subtotal Mismatch` or `VAT Breakdown Sum Mismatch`
**Symptoms**: Receipt appears in the Review Dashboard with a math validation error.
**Fix**: 
- **Check Column Alignment**: If using `glm-ocr`, ensure the "Two-Step Extraction" (ADR-005) is active. This uses Markdown tables to preserve column structure, which is the most common cause of math errors.
- **Swiss Rounding**: If the difference is only 0.01–0.04 CHF, it is likely a 5-rappen rounding artifact. Correct the value in the dashboard and push.
- **Resolution**: If text is blurry, ensure `OCR_ENGINE=glm-ocr` and that the image resolution is high enough (the app automatically caps at 2560px, which is optimal).

### 6. `Malformed JSON / Extraction Failed`
**Symptoms**: Logs show `JSONDecodeError` or "LLM failed to return structured data".
**Fix**: 
- **Markdown Tables**: The pipeline now expects Markdown-formatted OCR text for GLM. If the vision model fails to provide this, extraction might fail.
- **Model Choice**: Ensure you are using a vision-capable model (e.g., `glm-ocr`) for the OCR step and a strong parser (e.g., `qwen3.5:9b`) for extraction.

### VAT Math Mismatch Errors
If the review queue shows `VAT breakdown total (X) ≠ extracted VAT amount (Y)`:
1. **Column Shift**: Check the `ocr_text` in the review file. If the numbers are under the wrong headers (e.g. VAT amount under "Base"), ensure `extraction.py` has the latest "shifted column" guidance.
2. **Resolution**: If the text is blurry, ensure `OCR_MAX_LONG_EDGE` is at least 2560px.
3. **Contrast**: Very faint thermal receipts may require increasing the contrast enhancement in `ocr.py` (currently 1.3x).

### GLM-OCR Latency (Timeout)
If the pipeline hangs or times out during OCR:
1. **Payload Size**: Large images are resized to 2560px. If still too slow, ensure your Ollama instance is running on a GPU.
2. **WebP Encoding**: The system uses WebP for speed and sharpness. If your environment lacks `libwebp`, it may fall back to slow JPEG encoding.
3. **Prompt Interference**: Do not add natural language instructions to the GLM prompt. Only use the canonical `"Text Recognition:"` trigger to ensure the model uses its optimized internal pipeline.

### 7. `Merchant Match Failure`
**Symptoms**: Extracted merchant name is correct, but it doesn't match an existing contact in bexio.
**Fix**: 
- If the merchant is new, bexio-receipts will attempt to create a contact.
- If it fails, manually create the contact in bexio and then update the mapping in the dashboard.

### 8. `Handwritten or Non-Latin Receipts`
**Symptoms**: `paddleocr` (default) fails to recognize text.
**Fix**: 
- Switch to `OCR_ENGINE=glm-ocr` in your `.env`. GLM-OCR is a multimodal model that performs significantly better on handwritten and complex documents.

## Ingestion Specific Issues

- **Email Ingestion**: Check if your IMAP server requires "App Passwords" (common with Gmail/Outlook).
- **Google Drive**: If a file isn't picked up, ensure it's not a "Shortcut" or "Google Doc" format. The pipeline only replicates actual binary files (PDFs, PNGs, JPEGs).
- **Telegram**: If the bot doesn't respond, verify your User ID is in `TELEGRAM_ALLOWED_USERS`.

## Database Issues

If you need to **re-process** a receipt that was already filed:
1. Locate the file hash in `processed_receipts.db`.
2. Delete the record: `DELETE FROM processed_receipts WHERE file_hash = '...'`.
3. Re-run the ingestion.
