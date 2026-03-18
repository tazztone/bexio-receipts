import json
import logging
import mimetypes
from pathlib import Path

import structlog

from .ocr import async_run_ocr
from .extraction import extract_receipt
from .validation import validate_receipt
from .bexio_client import BexioClient
from .config import Settings
from .models import Receipt
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

async def send_to_review(file_path: str, raw_text: str, errors: list[str], settings: Settings, receipt: Receipt | None = None) -> dict:
    """Save problematic receipts to a review directory."""
    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    review_file = review_dir / f"{Path(file_path).stem}.json"
    
    review_data = {
        "original_file": str(file_path),
        "ocr_text": raw_text,
        "errors": errors,
        "extracted": receipt.model_dump(mode="json") if receipt else None,
    }
    
    with open(review_file, "w") as f:
        json.dump(review_data, f, indent=2, default=str)
    
    logger.warning(f"Receipt sent to review: {review_file}")
    return {"status": "review", "review_file": str(review_file)}

async def process_receipt(file_path: str, settings: Settings, bexio: BexioClient, db: DuplicateDetector) -> dict:
    """Full pipeline: OCR → Extract → Validate → Push."""
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # 0. Duplicate Detection
    file_hash = db.get_hash(file_path)
    existing_id = db.is_duplicate(file_hash)
    if existing_id:
        logger.warning(f"Duplicate receipt detected! Already processed with ID: {existing_id}")
        return {"status": "duplicate", "expense_id": existing_id}

    # 1. OCR
    logger.info(f"Running OCR ({settings.ocr_engine}) on {file_path}...")
    raw_text, avg_confidence, _ = await async_run_ocr(file_path, settings)
    
    if avg_confidence < settings.ocr_confidence_threshold:
        return await send_to_review(file_path, raw_text, [f"Low OCR confidence: {avg_confidence:.1%}"], settings)
    
    # 2. LLM extraction
    logger.info("Extracting data via LLM...")
    try:
        receipt = await extract_receipt(raw_text, settings)
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return await send_to_review(file_path, raw_text, [f"LLM extraction failed: {str(e)}"], settings)
    
    # 3. Validation
    logger.info("Validating extracted data...")
    errors = validate_receipt(receipt, settings)
    if errors:
        return await send_to_review(file_path, raw_text, errors, settings, receipt)
    
    # 4. Push to bexio
    logger.info("Pushing to bexio...")
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"
        
        file_uuid = await bexio.upload_file(file_path, file_path_obj.name, mime_type)
        
        # Ensure default account IDs are set
        if not settings.default_booking_account_id:
             return await send_to_review(file_path, raw_text, ["Missing default booking account ID in settings"], settings, receipt)

        # Prefer Bill (v4) if we have a merchant name, otherwise fall back to simple Expense (v4)
        if receipt.merchant_name:
            logger.info(f"Creating Purchase Bill for {receipt.merchant_name}...")
            
            # Smart Account Mapping: lookup last used account for this merchant
            booking_account_id = db.get_merchant_account(receipt.merchant_name) or settings.default_booking_account_id
            
            expense = await bexio.create_purchase_bill(
                receipt, file_uuid,
                booking_account_id=booking_account_id
            )
            
            # Save mapping for next time
            db.set_merchant_account(receipt.merchant_name, booking_account_id)
        else:
            if not settings.default_bank_account_id:
                return await send_to_review(file_path, raw_text, ["Missing default bank account ID for simple expense"], settings, receipt)
            
            logger.info("No merchant name, creating simple Expense...")
            expense = await bexio.create_expense(
                receipt, file_uuid,
                booking_account_id=settings.default_booking_account_id,
                bank_account_id=settings.default_bank_account_id,
            )
        
        # 5. Mark as processed
        db.mark_processed(file_hash, file_path, str(expense.get("id")))

        logger.info(f"Successfully booked expense {expense.get('id')} in bexio.")
        return {"status": "booked", "expense_id": expense.get("id"), "receipt": receipt.model_dump(mode="json")}
    except Exception as e:
        logger.error(f"Failed to push to bexio: {e}")
        return await send_to_review(file_path, raw_text, [f"bexio API error: {str(e)}"], settings, receipt)
