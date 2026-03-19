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

def setup_logging(env: str = "development"):
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
    ]

    if env == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

async def process_file(file_path: str, dry_run: bool):
    logger = structlog.get_logger("bexio_receipts.cli")
    
    if not Path(file_path).exists():
        logger.error("File not found", path=file_path)
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
        
        errors = validate_receipt(receipt, settings)
        if errors:
            print("\n--- Validation Errors ---\n" + "\n".join(f"- {e}" for e in errors) + "\n")
        else:
            print("\n--- Validation Passed ---")
        return

    # Real run
    if not settings.bexio_api_token:
        logger.error("BEXIO_API_TOKEN is not set.")
        sys.exit(1)

    from .database import DuplicateDetector
    db = DuplicateDetector(settings.database_path)

    async with BexioClient(token=settings.bexio_api_token, base_url=settings.bexio_base_url) as client:
        await client.cache_lookups()
        result = await process_receipt(file_path, settings, client, db)
        print(f"\nFinal Result:\n{json.dumps(result, indent=2, default=str)}")

def main():
    global settings
    from .config import Settings
    if settings is None:
        settings = Settings()

    setup_logging(settings.env)
    parser = argparse.ArgumentParser(description="bexio-receipts: Automate receipt ingestion into bexio.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process a single receipt file")
    process_parser.add_argument("file", help="Path to the receipt file")
    process_parser.add_argument("--dry-run", action="store_true", help="OCR and extraction only")

    # Mappings command
    export_parser = subparsers.add_parser("export-mappings", help="Export merchant account mappings to a JSON file")
    export_parser.add_argument("file", help="Path to the output JSON file")

    import_parser = subparsers.add_parser("import-mappings", help="Import merchant account mappings from a JSON file")
    import_parser.add_argument("file", help="Path to the input JSON file")

    # Reprocess command
    reprocess_parser = subparsers.add_parser("reprocess", help="Re-process a receipt from the review queue")
    reprocess_parser.add_argument("review_file", help="Path to the review JSON file")
    reprocess_parser.add_argument("--dry-run", action="store_true", help="OCR and extraction only")

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Start the review dashboard server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")

    # Watch-folder command
    watch_parser = subparsers.add_parser("watch-folder", help="Monitor a folder for new receipts")
    watch_parser.add_argument("--path", default=settings.inbox_path if settings else "./inbox", help=f"Path to monitor (default: {settings.inbox_path if settings else './inbox'})")

    # Watch-email command
    subparsers.add_parser("watch-email", help="Monitor an email inbox for new receipts")

    # Watch-telegram command
    subparsers.add_parser("watch-telegram", help="Monitor Telegram for new receipts")

    # Watch-gdrive command
    gdrive_parser = subparsers.add_parser("watch-gdrive", help="Monitor Google Drive for new receipts")
    gdrive_parser.add_argument("--folder-id", help="Override Google Drive folder ID")

    # Gdrive-auth command
    subparsers.add_parser("gdrive-auth", help="Run interactive Google Drive OAuth2 authentication")

    args = parser.parse_args()

    if args.command == "process":
        try:
            asyncio.run(process_file(args.file, args.dry_run))
        except KeyboardInterrupt:
            pass
    elif args.command == "reprocess":
        try:
            review_file = Path(args.review_file)
            if not review_file.exists():
                print(f"Review file {args.review_file} not found.")
                sys.exit(1)
            with open(review_file) as f:
                data = json.load(f)
            orig_file = data.get("original_file")
            if not orig_file or not Path(orig_file).exists():
                print(f"Original file {orig_file} not found.")
                sys.exit(1)
            asyncio.run(process_file(orig_file, args.dry_run))
        except KeyboardInterrupt:
            pass
    elif args.command == "export-mappings":
        from .database import DuplicateDetector
        db = DuplicateDetector(settings.database_path)
        mappings = db.get_all_merchant_accounts()
        with open(args.file, "w") as f:
            json.dump(mappings, f, indent=2)
        print(f"Exported {len(mappings)} mappings to {args.file}")
    elif args.command == "import-mappings":
        from .database import DuplicateDetector
        db = DuplicateDetector(settings.database_path)
        with open(args.file) as f:
            mappings = json.load(f)
        db.import_merchant_accounts(mappings)
        print(f"Imported {len(mappings)} mappings from {args.file}")
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
    elif args.command == "watch-telegram":
        from .telegram_bot import run_bot
        try:
            asyncio.run(run_bot(settings))
        except KeyboardInterrupt:
            pass
    elif args.command == "watch-gdrive":
        from .gdrive_ingest import watch_gdrive
        try:
            asyncio.run(watch_gdrive(settings, args.folder_id))
        except KeyboardInterrupt:
            pass
    elif args.command == "gdrive-auth":
        from .gdrive_ingest import run_gdrive_auth
        run_gdrive_auth(settings)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
