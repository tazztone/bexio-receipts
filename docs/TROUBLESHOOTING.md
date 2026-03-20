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

### 4. `Total/Subtotal Mismatch`
**Symptoms**: Receipt appears in the Review Dashboard with a "Total mismatch" error.
**Fix**: This is often due to the LLM misidentifying columns or Swiss VAT rounding (5-rappen). Correct the values in the dashboard and hit "Apply & Push".

### 5. `Malformed JSON / Extraction Failed`
**Symptoms**: Logs show `JSONDecodeError` or "LLM failed to return structured data".
**Fix**: 
- The LLM might be "hallucinating" or struggling with complex receipt layouts.
- Try switching to a more capable model (e.g., `qwen3.5:9b` or `openai`).
- Ensure the receipt image is clear and the OCR text is legible.

### 6. `Merchant Match Failure`
**Symptoms**: Extracted merchant name is correct, but it doesn't match an existing contact in bexio.
**Fix**: 
- If the merchant is new, bexio-receipts will attempt to create a contact.
- If it fails, manually create the contact in bexio and then update the mapping in the dashboard.

### 7. `Handwritten or Non-Latin Receipts`
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
