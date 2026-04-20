# Troubleshooting Guide

## Common Errors & Fixes

### 1. `GLM-OCR SDK Connection Error`
**Symptoms**: `httpx.ConnectError` or 500 errors during OCR.
**Fix**:
- Ensure the vLLM/SGLang backend is running.
- Verify `GLM_OCR_API_HOST` and `GLM_OCR_API_PORT` in your `.env`.
- Check if the layout analysis device (`GLM_OCR_LAYOUT_DEVICE`) is correct.

### 3. `bexio 401 Unauthorized`
**Symptoms**: Receipt extraction works, but pushing to bexio fails with 401.
**Fix**:
- Your PAT (Personal Access Token) is expired or invalid.
- Ensure the token has `expense_show`, `expense_create`, and `file_show`
  permissions.

### 4. `Security: Password rejected`
**Symptoms**: Application fails to start with `ValueError: review_password must be changed...`.
**Fix**:
- If `ENV=production`, the validator ensures you have changed the default
  password.
- **Note**: The validator specifically checks for the literal string
  `password`. You should always set a strong, unique password.

### 5. `Total/Subtotal Mismatch` or `VAT Breakdown Sum Mismatch`
**Symptoms**: Receipt appears in the Review Dashboard with a math validation
error.
**Fix**:
- **Native Layout**: The GLM-OCR SDK uses PP-DocLayoutV3 to preserve column
  structure. Ensure your backend has enough memory for the layout analysis.
- **Swiss Rounding**: If the difference is only 0.01–0.04 CHF, it is likely a
  5-rappen rounding artifact. Correct the value in the dashboard and push.
- **Resolution**: If text is blurry, ensure the image resolution is high enough
  (the app automatically caps at 2560px).

### 6. `Malformed JSON / Extraction Failed`
**Symptoms**: Logs show `JSONDecodeError` or "LLM failed to return structured
data".
**Fix**:
- **Markdown Tables**: The pipeline now expects Markdown-formatted OCR text for
  GLM. If the vision model fails to provide this, extraction might fail.
- **Model Choice**: Ensure the vLLM backend is using the GLM-OCR model and your
  extraction provider (Ollama/OpenAI) is using a strong parser (e.g., 
  `qwen3.5:9b`).

### VAT Math Mismatch Errors
If the review queue shows `VAT breakdown total (X) ≠ extracted VAT amount (Y)`:
1. **Column Shift**: Check the `ocr_text` in the review file. If the numbers
   are under the wrong headers (e.g. VAT amount under "Base"), ensure
   `extraction.py` has the latest "shifted column" guidance.
2. **Resolution**: If the text is blurry, ensure `OCR_MAX_LONG_EDGE` is at least
   2560px.
3. **Contrast**: Very faint thermal receipts may require increasing the
   contrast enhancement in `ocr.py` (currently 1.3x).

### GLM-OCR Latency (Timeout)
If the pipeline hangs or times out during OCR:
1. **GPU Acceleration**: GLM-OCR is a heavy model. Ensure the vLLM backend is 
   running on a GPU.
2. **WebP Encoding**: The system uses WebP for speed and sharpness.
3. **Timeout**: Increase `GLM_OCR_TIMEOUT` if processing multi-page PDFs.

### 7. `Merchant Match Failure`
**Symptoms**: Extracted merchant name is correct, but it doesn't match an
existing contact in bexio.
**Fix**:
- If the merchant is new, bexio-receipts will attempt to create a contact.
- If it fails, manually create the contact in bexio and then update the mapping
  in the dashboard.
### 8. `Account Classification Mismatch`
**Symptoms**: The suggested booking account is wrong (e.g., 4201 instead of 4200).
**Fix**:
- **Manual Override**: Change the account in the Review Dashboard dropdown before
  pushing.
- **Learning Loop**: When you push with the corrected account, the system
  remembers the `(merchant, vat_rate)` pair. Future receipts for this merchant
  will use your choice automatically.
- **AI Context**: If the AI reasoning seems confused, check the `BEXIO_ACCOUNTS`
  descriptions in your `.env`. Clearer descriptions (e.g. "Food only") help the
  classifier.

## Ingestion Specific Issues

- **Google Drive**: If a file isn't picked up, ensure it's not a "Shortcut" or
  "Google Doc" format. The pipeline only replicates actual binary files (PDFs,
  PNGs, JPEGs).

## Database Issues

If you need to **re-process** a receipt that was already filed:
1. Locate the file hash in `processed_receipts.db`.
2. Delete the record: `DELETE FROM processed_receipts WHERE file_hash = '...'`.
3. Re-run the ingestion.
