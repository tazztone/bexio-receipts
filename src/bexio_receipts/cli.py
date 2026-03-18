import argparse
import asyncio
import logging
import sys
import json
from pathlib import Path
import uvicorn

import structlog

from .config import settings
from .bexio_client import BexioClient
from .pipeline import process_receipt
from .server import app

def setup_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

async def process_file(file_path: str, dry_run: bool):
    logger = structlog.get_logger("bexio_receipts.cli")
    
    if not Path(file_path).exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    if dry_run:
        logger.info("Dry run: OCR and Extraction only.")
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
    setup_logging()
    parser = argparse.ArgumentParser(description="bexio-receipts: Automate receipt ingestion into bexio.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process a single receipt file")
    process_parser.add_argument("file", help="Path to the receipt file")
    process_parser.add_argument("--dry-run", action="store_true", help="OCR and extraction only")

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Start the review dashboard server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")

    # Watch-folder command
    watch_parser = subparsers.add_parser("watch-folder", help="Monitor a folder for new receipts")
    watch_parser.add_argument("--path", default="./inbox", help="Path to monitor")

    # Watch-email command
    email_parser = subparsers.add_parser("watch-email", help="Monitor an email inbox for new receipts")

    args = parser.parse_args()

    if args.command == "process":
        try:
            asyncio.run(process_file(args.file, args.dry_run))
        except KeyboardInterrupt:
            pass
    elif args.command == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "watch-folder":
        from .watcher import watch_folder
        try:
            asyncio.run(watch_folder(args.path, settings))
        except KeyboardInterrupt:
            pass
    elif args.command == "watch-email":
        from .email_ingest import watch_email
        try:
            asyncio.run(watch_email(settings))
        except KeyboardInterrupt:
            pass
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
