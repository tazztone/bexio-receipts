import asyncio
import json
from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from .bexio_client import BexioClient
from .pipeline import process_receipt
from .config import Settings

app = typer.Typer(
    help="bexio-receipts: Automate receipt ingestion into bexio.",
    rich_markup_mode="rich",
)
watch_app = typer.Typer(help="Ingestion source watchers.")
mapping_app = typer.Typer(help="Merchant account mapping management.")
app.add_typer(watch_app, name="watch")
app.add_typer(mapping_app, name="mapping")

console = Console()


def setup_logging(env: str = "development", quiet: bool = False):
    import logging
    from typing import Any, List

    level = logging.WARNING if quiet else logging.INFO

    processors: List[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
    ]

    if env == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_settings() -> Settings:
    from pydantic import ValidationError

    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        console.print("[red]Configuration error: Missing or invalid settings.[/red]")
        for err in e.errors():
            loc = ".".join(map(str, err.get("loc", [])))
            msg = err.get("msg", "")
            console.print(f"  - [bold]{loc}[/bold]: {msg}")
        console.print(
            "\n[yellow]Run [bold]bexio-receipts init[/bold] to set up your configuration.[/yellow]"
        )
        raise typer.Exit(code=1)


@app.command()
def init():
    """Interactive setup wizard to create .env file."""
    console.print(Panel.fit("Welcome to bexio-receipts setup! 🧾🚀", style="bold blue"))

    env_path = Path(".env")
    if env_path.exists():
        if not Confirm.ask("An .env file already exists. Overwrite?"):
            raise typer.Exit()

    token = Prompt.ask("Enter your Bexio API Token (from bexio Admin -> API Tokens)")
    ocr_engine = Prompt.ask(
        "OCR Engine", choices=["glm-ocr", "paddleocr"], default="glm-ocr"
    )
    llm_provider = Prompt.ask(
        "LLM Provider", choices=["ollama", "openai"], default="ollama"
    )

    config = [
        f"BEXIO_API_TOKEN={token}",
        "BEXIO_BASE_URL=https://api.bexio.com",
        f"OCR_ENGINE={ocr_engine}",
        f"LLM_PROVIDER={llm_provider}",
    ]

    if ocr_engine == "glm-ocr":
        config.append("GLM_OCR_URL=http://localhost:11434")
        config.append("GLM_OCR_MODEL=glm-ocr")

    if llm_provider == "ollama":
        config.append("OLLAMA_URL=http://localhost:11434")
        config.append("LLM_MODEL=qwen3.5:9b")

    config.append("DEFAULT_BOOKING_ACCOUNT_ID=630")
    config.append("DEFAULT_BANK_ACCOUNT_ID=1")
    config.append(
        "SECRET_KEY="
        + Prompt.ask(
            "Secret Key (for dashboard sessions)", default="change-me-in-production"
        )
    )

    with open(env_path, "w") as f:
        f.write("\n".join(config) + "\n")

    console.print("[green]Successfully created .env file![/green]")


@app.command()
def process(
    file: Path = typer.Argument(..., help="Path to the receipt file", exists=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="OCR and extraction only"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimize log output"),
):
    """Process a single receipt file."""
    settings = get_settings()
    setup_logging(settings.env, quiet=quiet)

    async def _run():
        if dry_run:
            from .ocr import async_run_ocr
            from .extraction import extract_receipt
            from .validation import validate_receipt

            raw_text, avg_confidence, _ = await async_run_ocr(str(file), settings)
            console.print(f"\n[bold]OCR Confidence:[/bold] {avg_confidence:.1%}")
            console.print(f"\n[bold]Raw OCR Text:[/bold]\n{raw_text}\n")

            receipt = await extract_receipt(raw_text, settings)
            console.print(
                f"\n[bold]Extracted Data:[/bold]\n{receipt.model_dump_json(indent=2)}\n"
            )

            errors = validate_receipt(receipt, settings)
            if errors:
                console.print(
                    "\n[bold red]Validation Errors:[/bold red]\n"
                    + "\n".join(f"- {e}" for e in errors)
                )
            else:
                console.print("\n[bold green]Validation Passed[/bold green]")
            return

        from .database import DuplicateDetector

        db = DuplicateDetector(settings.database_path)

        async with BexioClient(
            token=settings.bexio_api_token,
            base_url=settings.bexio_base_url,
            default_vat_rate=settings.default_vat_rate,
        ) as client:
            await client.cache_lookups()
            result = await process_receipt(str(file), settings, client, db)
            console.print(
                f"\n[bold]Final Result:[/bold]\n{json.dumps(result, indent=2, default=str)}"
            )

    asyncio.run(_run())


@app.command()
def reprocess(
    review_file: Path = typer.Argument(
        ..., help="Path to the review JSON file", exists=True
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="OCR and extraction only"),
):
    """Re-process a receipt from the review queue."""
    settings = get_settings()
    setup_logging(settings.env)

    with open(review_file) as f:
        data = json.load(f)

    orig_file = data.get("original_file")
    if not orig_file or not Path(orig_file).exists():
        console.print(f"[red]Original file {orig_file} not found.[/red]")
        raise typer.Exit(1)

    async def _run():
        if dry_run:
            from .ocr import async_run_ocr
            from .extraction import extract_receipt
            from .validation import validate_receipt

            raw_text, avg_confidence, _ = await async_run_ocr(orig_file, settings)
            console.print(f"\n[bold]OCR Confidence:[/bold] {avg_confidence:.1%}")
            console.print(f"\n[bold]Raw OCR Text:[/bold]\n{raw_text}\n")

            receipt = await extract_receipt(raw_text, settings)
            console.print(
                f"\n[bold]Extracted Data:[/bold]\n{receipt.model_dump_json(indent=2)}\n"
            )

            errors = validate_receipt(receipt, settings)
            if errors:
                console.print(
                    "\n[bold red]Validation Errors:[/bold red]\n"
                    + "\n".join(f"- {e}" for e in errors)
                )
            else:
                console.print("\n[bold green]Validation Passed[/bold green]")
            return

        from .database import DuplicateDetector

        db = DuplicateDetector(settings.database_path)

        async with BexioClient(
            token=settings.bexio_api_token,
            base_url=settings.bexio_base_url,
            default_vat_rate=settings.default_vat_rate,
        ) as client:
            await client.cache_lookups()
            result = await process_receipt(orig_file, settings, client, db)
            console.print(
                f"\n[bold]Final Result:[/bold]\n{json.dumps(result, indent=2, default=str)}"
            )

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
):
    """Start the review dashboard server."""
    import uvicorn
    from .server import app as fastapi_app

    settings = get_settings()
    setup_logging(settings.env)
    uvicorn.run(fastapi_app, host=host, port=port)


@watch_app.command("folder")
def watch_folder(path: Optional[Path] = typer.Option(None, help="Path to monitor")):
    """Monitor a folder for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)
    from .watcher import watch_folder as _watch

    asyncio.run(_watch(str(path or settings.inbox_path), settings))


@watch_app.command("email")
def watch_email():
    """Monitor an email inbox for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)
    from .email_ingest import watch_email as _watch

    asyncio.run(_watch(settings))


@watch_app.command("telegram")
def watch_telegram():
    """Monitor Telegram for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)
    from .telegram_bot import run_bot

    asyncio.run(run_bot(settings))


@watch_app.command("gdrive")
def watch_gdrive(
    folder_id: Optional[str] = typer.Option(
        None, help="Override Google Drive folder ID"
    ),
):
    """Monitor Google Drive for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)
    from .gdrive_ingest import watch_gdrive as _watch

    asyncio.run(_watch(settings, folder_id))


@app.command()
def gdrive_auth():
    """Run interactive Google Drive OAuth2 authentication."""
    settings = get_settings()
    from .gdrive_ingest import run_gdrive_auth

    run_gdrive_auth(settings)


@mapping_app.command("export")
def export_mappings(
    file: Path = typer.Argument(..., help="Path to the output JSON file"),
):
    """Export merchant account mappings to a JSON file."""
    settings = get_settings()
    from .database import DuplicateDetector

    db = DuplicateDetector(settings.database_path)
    mappings = db.get_all_merchant_accounts()
    with open(file, "w") as f:
        json.dump(mappings, f, indent=2)
    console.print(f"Exported {len(mappings)} mappings to {file}")


@mapping_app.command("import")
def import_mappings(
    file: Path = typer.Argument(..., help="Path to the input JSON file", exists=True),
):
    """Import merchant account mappings from a JSON file."""
    settings = get_settings()
    from .database import DuplicateDetector

    db = DuplicateDetector(settings.database_path)
    with open(file) as f:
        mappings = json.load(f)
    db.import_merchant_accounts(mappings)
    console.print(f"Imported {len(mappings)} mappings from {file}")


def main():
    app()


if __name__ == "__main__":
    main()
