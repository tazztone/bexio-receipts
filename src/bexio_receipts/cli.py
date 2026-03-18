import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import settings
from .bexio_client import BexioClient
from .pipeline import process_receipt

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

async def main_async():
    parser = argparse.ArgumentParser(description="bexio Receipt Pipeline CLI")
    parser.add_argument("file", help="Path to the receipt file (image or PDF)")
    parser.add_argument("--dry-run", action="store_true", help="OCR and extraction only, do not push to bexio")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("bexio_receipts.cli")

    file_path = args.file
    if not Path(file_path).exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    if args.dry_run:
        logger.info("Dry run: OCR and Extraction only.")
        # We can implement a dry run mode in pipeline or just mock the client
        # For now, let's just use the pipeline but bypass the final push
        # Actually, let's just implement it in a simple way here
        from .ocr import async_run_ocr
        from .extraction import extract_receipt
        from .validation import validate_receipt

        raw_text, avg_confidence, _ = await async_run_ocr(file_path, settings)
        print(f"\n--- OCR Confidence: {avg_confidence:.1%} ---")
        print(f"\n--- Raw OCR Text ---\n{raw_text}\n")
        
        receipt = await extract_receipt(raw_text, settings)
        print(f"\n--- Extracted Data ---\n{receipt.model_dump_json(indent=2)}\n")
        
        errors = validate_receipt(receipt)
        if errors:
            print(f"\n--- Validation Errors ---\n" + "\n".join(f"- {e}" for e in errors) + "\n")
        else:
            print("\n--- Validation Passed ---")
        
        return

    # Real run
    if not settings.bexio_api_token:
        logger.error("BEXIO_API_TOKEN is not set.")
        sys.exit(1)

    client = BexioClient(token=settings.bexio_api_token, base_url=settings.bexio_base_url)
    try:
        await client.cache_lookups()
        result = await process_receipt(file_path, settings, client)
        print(f"\nFinal Result:\n{json.dumps(result, indent=2, default=str)}")
    finally:
        await client.close()

def main():
    import json # locally for result printing
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
