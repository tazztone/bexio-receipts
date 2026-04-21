"""
Main processing pipeline for bexio-receipts.
Orchestrates OCR, LLM extraction, validation, and Bexio API calls.
"""

import json
from pathlib import Path

import httpx
import structlog

from .bexio_client import BexioClient
from .config import Settings
from .database import DuplicateDetector as Database
from .extraction import (
    ExtractionError,
    ExtractionTrace,
    classify_accounts,
    extract_receipt,
)
from .models import Receipt
from .ocr import async_run_ocr
from .validation import validate_receipt

logger = structlog.get_logger(__name__)


def decide_bexio_action(receipt: Receipt) -> str:
    """
    Decide whether to create a simple 'expense' or a 'purchase_bill'.
    Heuristic: Use bill if we have a merchant name or multiple VAT entries.
    """
    if receipt.merchant_name:
        return "purchase_bill"
    if receipt.vat_breakdown and len(receipt.vat_breakdown) > 1:
        return "purchase_bill"
    return "expense"


async def send_to_review(
    file_path: str,
    raw_text: str,
    errors: list[str],
    settings: Settings,
    receipt: Receipt | None = None,
    ocr_confidence: float | None = None,
    failed_stage: str = "unknown",
    bexio_action: str | None = None,
    trace: ExtractionTrace | None = None,
) -> dict:
    """Save problematic receipts to a review directory."""
    try:
        review_dir = Path(settings.review_dir)
        review_dir.mkdir(exist_ok=True, parents=True)
        review_file = review_dir / f"{Path(file_path).stem}.json"

        review_data = {
            "original_file": str(file_path),
            "ocr_text": raw_text,
            "ocr_confidence": ocr_confidence,
            "failed_stage": trace.error_stage
            if trace and trace.error_stage
            else failed_stage,
            "errors": errors,
            "bexio_action": bexio_action,
            "extraction_trace": trace.model_dump(mode="json") if trace else None,
            "extracted": receipt.model_dump(mode="json") if receipt else None,
        }

        with open(review_file, "w") as f:
            json.dump(review_data, f, indent=2, default=str)

        # Save raw OCR text for debugging
        try:
            ocr_file = review_dir / f"{Path(file_path).stem}.ocr.md"
            ocr_file.write_text(raw_text)
        except Exception as e:
            logger.warning("Failed to save review OCR file", error=str(e))

        logger.warning(
            "Receipt sent to review",
            review_file=str(review_file),
            errors=errors,
        )
        return {"status": "review", "review_file": str(review_file)}
    except Exception as e:
        logger.error("Failed to save review file, logging fallback data", error=str(e))
        logger.warning(
            "Review Fallback",
            original_file=file_path,
            errors=errors,
            extracted=receipt.model_dump() if receipt else None,
        )
        return {"status": "review_failed", "errors": errors}


async def process_receipt(
    file_path: str,
    settings: Settings,
    bexio: BexioClient,
    db: Database,
    mime_type: str | None = None,
    push_confirmed: bool = False,
) -> dict:
    """
    Full pipeline for a single receipt file.
    """
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    # Duplicate check via file hash
    file_hash = db.get_hash(file_path)
    existing_id = db.is_duplicate(file_hash)
    if existing_id:
        logger.warning(
            "Duplicate receipt detected", expense_id=existing_id, path=file_path
        )
        return {"status": "duplicate", "expense_id": existing_id}

    # 1. OCR / One-shot Extraction
    logger.info("Running OCR/Extraction", path=file_path)
    # Use a shared client for all HTTP stages (OCR, LLM, Bexio)
    # Max timeout covers the longest possible individual stage
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0,
            read=max(settings.llm_timeout, 60.0),
            write=5.0,
            pool=2.0,
        )
    ) as client:
        avg_confidence: float = 0.0
        try:
            raw_text, avg_confidence, _ = await async_run_ocr(file_path, settings)
        except (TimeoutError, httpx.TimeoutException):
            error_msg = "OCR stage timed out"
            logger.error(error_msg, path=file_path)
            return await send_to_review(
                file_path, "", [error_msg], settings, failed_stage="ocr"
            )
        except Exception as e:
            error_msg = f"OCR failed: {e!s}"
            logger.error(error_msg, path=file_path)
            return await send_to_review(
                file_path, "", [error_msg], settings, failed_stage="ocr"
            )

        # Initialize structured trace after OCR
        trace = ExtractionTrace(ocr_text=raw_text)

        # 2. Extract structured data
        logger.info("Extracting data via LLM", model=settings.llm_model)

        # Save OCR text for audit/debugging even on success
        try:
            ocr_file = Path(file_path).with_suffix(".ocr.md")
            ocr_file.write_text(raw_text)
        except Exception as e:
            logger.warning("Failed to save audit OCR file", error=str(e))

        receipt = None
        try:
            receipt, trace = await extract_receipt(raw_text, settings, client=client)
        except (TimeoutError, httpx.TimeoutException):
            error_msg = "LLM extraction stage timed out"
            logger.error(error_msg, path=file_path)
            return await send_to_review(
                file_path,
                raw_text,
                [error_msg],
                settings,
                ocr_confidence=avg_confidence,
                failed_stage="extraction",
            )
        except ExtractionError as e:
            logger.error(
                "LLM extraction failed",
                error=str(e),
                trace=e.trace.model_dump() if e.trace else None,
            )
            return await send_to_review(
                file_path,
                raw_text,
                [f"LLM extraction failed: {e!s}"],
                settings,
                ocr_confidence=avg_confidence,
                failed_stage="extraction",
                trace=e.trace,
            )
        except Exception as e:
            logger.error("Unexpected error during extraction", error=str(e))
            return await send_to_review(
                file_path,
                raw_text,
                [f"Unexpected error: {e!s}"],
                settings,
                ocr_confidence=avg_confidence,
                failed_stage="extraction",
            )

        # 3. Step 3: Account Classification (Post-Extraction)
        logger.info("Classifying accounts via LLM", merchant=receipt.merchant_name)
        assignments = await classify_accounts(
            receipt, raw_text, settings, client=client, trace=trace
        )
        trace.step3_assignments = [a.model_dump() for a in assignments]

    # 4. Validation
    logger.info("Validating extracted data")
    errors, warnings = validate_receipt(receipt, settings)
    if errors:
        return await send_to_review(
            file_path,
            raw_text,
            errors,
            settings,
            receipt,
            ocr_confidence=avg_confidence,
            failed_stage="validation",
            trace=trace,
        )

    if warnings:
        logger.warning("Receipt has warnings (not blocking booking)", warnings=warnings)

    # 4. Push to bexio
    bexio_action = decide_bexio_action(receipt)
    if not push_confirmed:
        logger.info("Push not confirmed, sending to review queue", action=bexio_action)
        return await send_to_review(
            file_path,
            raw_text,
            [f"Push gate: BEXIO_PUSH_ENABLED=false. Would be: {bexio_action}"],
            settings,
            receipt,
            ocr_confidence=avg_confidence,
            failed_stage="safety_gate",
            bexio_action=bexio_action,
            trace=trace,
        )

    logger.info("Pushing to bexio", action=bexio_action)
    try:
        mime_type = mime_type or "application/octet-stream"

        file_uuid = await bexio.upload_file(file_path, file_path_obj.name, mime_type)

        # Ensure default account IDs are set
        if not settings.default_booking_account_id:
            return await send_to_review(
                file_path,
                raw_text,
                ["Missing default booking account ID in settings"],
                settings,
                receipt,
                ocr_confidence=avg_confidence,
                failed_stage="bexio",
                trace=trace,
            )

        # Prefer Bill (v4) if we have a merchant name or multiple VAT rates.
        if bexio_action == "purchase_bill":
            # Build booking account list based on assignments or database priority
            booking_account_ids = []
            if receipt.vat_breakdown:
                for entry in receipt.vat_breakdown:
                    acc_id = None
                    # Priority 1: Database (Learned from human)
                    if receipt.merchant_name:
                        acc_id = db.get_merchant_vat_account(
                            receipt.merchant_name, entry.rate
                        )

                    # Priority 2: LLM Assignment (Step 3)
                    if not acc_id:
                        # Find matching assignment
                        match = next(
                            (a for a in assignments if a.vat_rate == entry.rate), None
                        )
                        if match:
                            acc_id = int(match.account_id)

                    # Priority 3: Default fallback
                    if not acc_id:
                        logger.warning(
                            "No account found for VAT rate, using default",
                            rate=entry.rate,
                            merchant=receipt.merchant_name,
                        )
                        acc_id = settings.default_booking_account_id

                    booking_account_ids.append(acc_id)
            else:
                # Single rate or no breakdown
                acc_id = None
                if receipt.merchant_name:
                    acc_id = db.get_merchant_account(receipt.merchant_name)
                if not acc_id:
                    acc_id = settings.default_booking_account_id
                booking_account_ids = [acc_id]

            expense = await bexio.create_purchase_bill(
                receipt, file_uuid, booking_account_ids=booking_account_ids
            )
        else:
            if not settings.default_bank_account_id:
                return await send_to_review(
                    file_path,
                    raw_text,
                    ["Missing default bank account ID for simple expense"],
                    settings,
                    receipt,
                    ocr_confidence=avg_confidence,
                    failed_stage="bexio",
                    trace=trace,
                )

            expense = await bexio.create_expense(
                receipt,
                file_uuid,
                booking_account_id=settings.default_booking_account_id,
                bank_account_id=settings.default_bank_account_id,
            )

        # 5. Mark as processed
        db.mark_processed(
            file_hash,
            file_path,
            str(expense.get("id")),
            total_incl_vat=receipt.total_incl_vat,
            merchant_name=receipt.merchant_name,
            vat_amount=receipt.vat_amount,
            ocr_confidence=avg_confidence,
        )

        # Persist trace on success if debugging
        if settings.env == "development":
            try:
                debug_dir = Path("debug")
                debug_dir.mkdir(exist_ok=True, parents=True)
                (debug_dir / f"{file_path_obj.stem}_trace.json").write_text(
                    trace.model_dump_json(indent=2)
                )
            except Exception as de:
                logger.warning("Failed to save debug trace", error=str(de))

        logger.info(
            "Successfully booked expense in bexio", expense_id=expense.get("id")
        )
        return {
            "status": "booked",
            "expense_id": expense.get("id"),
            "receipt": receipt.model_dump(mode="json"),
        }
    except Exception as e:
        logger.error("Failed to push to bexio", error=str(e))
        return await send_to_review(
            file_path,
            raw_text,
            [f"bexio API error: {e!s}"],
            settings,
            receipt,
            ocr_confidence=avg_confidence,
            failed_stage="bexio",
            trace=trace,
        )
