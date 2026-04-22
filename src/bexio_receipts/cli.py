import asyncio
import json
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .bexio_client import BexioClient
from .config import Settings
from .pipeline import process_receipt

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
    from typing import Any

    level = logging.WARNING if quiet else logging.INFO

    processors: list[Any] = [
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
        return Settings()
    except ValidationError as e:
        console.print("[red]Configuration error: Missing or invalid settings.[/red]")
        is_missing_token = False
        for err in e.errors():
            loc = ".".join(map(str, err.get("loc", [])))
            msg = err.get("msg", "")
            console.print(f"  - [bold]{loc}[/bold]: {msg}")
            if "bexio_api_token" in loc:
                is_missing_token = True

        if is_missing_token:
            console.print(
                "\n[yellow]💡 Tip: Run [bold]bexio-receipts init[/bold] to set up your Bexio API token.[/yellow]"
            )
        else:
            console.print(
                "\n[yellow]Run [bold]bexio-receipts init[/bold] to update your configuration.[/yellow]"
            )
        raise typer.Exit(code=1) from None


@app.command()
def init(
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Skip prompts and use defaults/env vars"
    ),
    use_defaults: bool = typer.Option(
        False, "--defaults", help="Use default values for optional settings"
    ),
    quickstart: bool = typer.Option(
        False, "--quickstart", help="One-shot setup with defaults and a demo receipt"
    ),
):
    """Interactive setup wizard to create .env file."""
    if quickstart:
        non_interactive = True

    console.print(Panel.fit("Welcome to bexio-receipts setup! 🧾🚀", style="bold blue"))

    env_path = Path(".env")
    if (
        env_path.exists()
        and not non_interactive
        and not Confirm.ask("An .env file already exists. Overwrite?")
    ):
        raise typer.Exit()

    if non_interactive:
        import os

        token = os.getenv("BEXIO_API_TOKEN", "your_bexio_token")
        llm_provider = os.getenv("LLM_PROVIDER", "ollama")
        secret_key = os.getenv("SECRET_KEY", "change-me-in-production")

        console.print("\n[bold]Using assumed configuration:[/bold]")
        console.print(f"  - LLM: [cyan]{llm_provider}[/cyan]")
        console.print("  - Default Accounts: [cyan]630/1[/cyan]")
    else:
        token = Prompt.ask(
            "Enter your Bexio API Token (from bexio Admin -> API Tokens)"
        )

        # Live validation
        with console.status("[bold green]Validating token..."):

            async def validate():
                try:
                    async with BexioClient(token=token) as client:
                        profile = await client.get_profile()
                        return profile.get("company_name") or profile.get("name")
                except Exception:
                    return None

            company_name = asyncio.run(validate())

        if company_name:
            console.print(
                f"[green]✅ Token valid! Connected to: [bold]{company_name}[/bold][/green]"
            )
        else:
            console.print(
                "[red]❌ Token validation failed. Please check your token and try again.[/red]"
            )
            if not Confirm.ask("Continue anyway?"):
                raise typer.Exit(1)

        llm_provider = Prompt.ask(
            "LLM Provider",
            choices=["ollama", "openai", "openrouter"],
            default="ollama",
            show_choices=True,
        )

        openrouter_key = ""
        openrouter_model = "anthropic/claude-3.5-sonnet"
        openai_key = ""

        if llm_provider == "ollama":
            console.print(
                "[dim](Note: supports Ollama quantization suffix, e.g. qwen3.5:9b for default, qwen3.5:9b-q4_K_M for lower RAM usage)[/dim]"
            )
        elif llm_provider == "openrouter":
            openrouter_key = Prompt.ask("OpenRouter API Key")
            console.print(
                "[dim]Note: OpenRouter models must use provider/model format.[/dim]\n"
                "[dim]Examples: anthropic/claude-3.5-sonnet, meta-llama/llama-3-70b-instruct, google/gemini-1.5-pro[/dim]"
            )
            openrouter_model = Prompt.ask(
                "LLM Model", default="anthropic/claude-3.5-sonnet"
            )
        elif llm_provider == "openai":
            openai_key = Prompt.ask("OpenAI API Key")

        secret_key = Prompt.ask(
            "Secret Key (for dashboard sessions)", default="change-me-in-production"
        )

    config = [
        f"BEXIO_API_TOKEN={token}",
        "BEXIO_BASE_URL=https://api.bexio.com",
        "OCR_ENGINE=glm-ocr",
        f"LLM_PROVIDER={llm_provider}",
    ]

    if llm_provider == "ollama":
        config.append("OLLAMA_URL=http://localhost:11434")
        config.append("LLM_MODEL=qwen3.5:9b")
    elif llm_provider == "openrouter":
        config.append("OPENROUTER_URL=https://openrouter.ai/api/v1")
        if not non_interactive:
            config.append(f"OPENROUTER_API_KEY={openrouter_key}")
            config.append(f"LLM_MODEL={openrouter_model}")
        else:
            config.append("LLM_MODEL=anthropic/claude-3.5-sonnet")
    elif llm_provider == "openai":
        if not non_interactive:
            config.append(f"OPENAI_API_KEY={openai_key}")
        config.append("LLM_MODEL=gpt-4o-mini")

    config.append("DEFAULT_BOOKING_ACCOUNT_ID=630")
    config.append("DEFAULT_BANK_ACCOUNT_ID=1")
    config.append(f"SECRET_KEY={secret_key}")
    config.append("REVIEW_USERNAME=admin")
    config.append("REVIEW_PASSWORD=admin")
    config.append("BEXIO_PUSH_ENABLED=false")

    with open(env_path, "w") as f:
        f.write("\n".join(config) + "\n")

    console.print("[green]Successfully created .env file![/green]")
    console.print(
        "[yellow]⚠ Default password 'admin' written to .env — change before production.[/yellow]"
    )

    if quickstart:
        console.print(
            "\n[bold blue]🚀 Quickstart: Processing demo receipt...[/bold blue]"
        )
        import shutil

        inbox_path = Path("inbox")
        inbox_path.mkdir(exist_ok=True)
        demo_receipt = Path("tests/fixtures/sample_receipt.png")
        if demo_receipt.exists():
            target = inbox_path / "demo_receipt.png"
            shutil.copy(demo_receipt, target)
            console.print(f"  - Copied demo receipt to [cyan]{target}[/cyan]")

            # Run dry-run process
            from .config import Settings

            # We need to reload settings since we just wrote .env
            os.environ["BEXIO_API_TOKEN"] = token  # Ensure it's in env for this process
            settings = Settings()

            async def _dry_run():
                from .models import RawReceipt, RawVatRow
                from .pipeline import assemble_receipt, get_processor

                processor = get_processor(settings)
                with console.status(
                    f"[bold green]Running demo ({settings.processor_mode})..."
                ):
                    result = await processor.process(str(target), settings)

                raw_receipt = RawReceipt(
                    merchant_name=result.merchant_name,
                    transaction_date=result.transaction_date,
                    total_incl_vat=result.total_incl_vat,
                    currency=result.currency,
                    vat_rows=[
                        RawVatRow(**v) if isinstance(v, dict) else v
                        for v in result.vat_rows
                    ],
                    account_assignments=result.account_assignments,
                )
                receipt = assemble_receipt(raw_receipt)
                console.print(
                    f"  - Detected Merchant: [bold]{receipt.merchant_name}[/bold]"
                )
                console.print(
                    f"  - Detected Total: [bold]{receipt.total_incl_vat} {receipt.currency}[/bold]"
                )

            asyncio.run(_dry_run())
            console.print("\n[bold green]✨ Quickstart complete![/bold green]")
            console.print("Next steps:")
            console.print(
                "  1. Run [bold]uv run bexio-receipts serve[/bold] to start the dashboard"
            )
            console.print(
                "  2. Open [link=http://localhost:8000/setup]http://localhost:8000/setup[/link] to verify health"
            )
        else:
            console.print(
                "[yellow]Warning: Demo receipt fixture not found. Skipping demo process.[/yellow]"
            )


@app.command()
def process(
    file: Path = typer.Argument(..., help="Path to the receipt file", exists=True),
    push: bool = typer.Option(False, "--push", help="Actually write to Bexio"),
    dry_run: bool = typer.Option(False, "--dry-run", help="OCR and extraction only"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimize log output"),
):
    """Process a single receipt file."""
    settings = get_settings()
    setup_logging(settings.env, quiet=quiet)
    asyncio.run(_process_interactive(str(file), settings, push, dry_run))


async def _process_interactive(
    file_path: str, settings: Settings, push: bool, dry_run: bool
):
    """Internal helper for CLI processing."""
    if dry_run:
        from .models import RawReceipt, RawVatRow
        from .pipeline import assemble_receipt, get_processor
        from .validation import validate_receipt

        processor = get_processor(settings)
        with console.status(f"[bold green]Processing via {settings.processor_mode}..."):
            result = await processor.process(file_path, settings)

        console.print(f"\n[bold]Raw Text:[/bold]\n{result.raw_text}\n")

        raw_receipt = RawReceipt(
            merchant_name=result.merchant_name,
            transaction_date=result.transaction_date,
            total_incl_vat=result.total_incl_vat,
            currency=result.currency,
            vat_rows=[
                RawVatRow(**v) if isinstance(v, dict) else v for v in result.vat_rows
            ],
            account_assignments=result.account_assignments,
            payment_method=result.payment_method,
        )
        receipt = None
        validation_errors = []
        try:
            receipt = assemble_receipt(raw_receipt)
        except Exception as e:
            validation_errors = [str(e)]

        table = Table(title="Extracted Data (Dry Run)", show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="magenta")

        for field, value in raw_receipt.model_dump().items():
            if field == "vat_breakdown" and value:
                table.add_row(
                    field,
                    "\n".join([
                        f"{v['rate']}%: {v['total_incl_vat']} (VAT: {v['vat_amount']})"
                        for v in value
                    ]),
                )
            elif field == "account_assignments" and value:
                table.add_row(
                    field,
                    "\n".join([
                        f"{a['vat_rate']}% -> {a['account_id']} ({a['reasoning']})"
                        for a in value
                    ]),
                )
            else:
                table.add_row(field, str(value))
        console.print(table)

        with console.status("[bold yellow]Validating..."):
            if receipt:
                errors, warnings = validate_receipt(receipt, settings)
                errors.extend(validation_errors)
            else:
                errors = validation_errors
                warnings = []

        if errors:
            console.print(
                "\n[bold red]Validation Errors:[/bold red]\n"
                + "\n".join(f"- {e}" for e in errors)
            )
        if warnings:
            console.print(
                "\n[bold yellow]Validation Warnings:[/bold yellow]\n"
                + "\n".join(f"- {w}" for w in warnings)
            )
        if not errors and not warnings:
            console.print("\n[bold green]Validation Passed[/bold green]")
        return

    if push and not settings.bexio_push_enabled:
        console.print(
            "[bold red]Error: BEXIO_PUSH_ENABLED=false in configuration.[/bold red]"
        )
        console.print("Set it to true in .env to enable writes via --push.")
        raise typer.Exit(1)

    from .database import DuplicateDetector

    db = DuplicateDetector(settings.database_path)

    async with BexioClient(
        token=settings.bexio_api_token,
        base_url=settings.bexio_base_url,
        default_vat_rate=settings.default_vat_rate,
        default_payment_terms_days=settings.default_payment_terms_days,
        push_enabled=settings.bexio_push_enabled,
    ) as client:
        with console.status("[bold blue]Connecting to Bexio..."):
            try:
                await client.cache_lookups()
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to connect to Bexio ({e}). Proceeding to OCR/Extraction...[/yellow]"
                )

        with console.status("[bold green]Processing receipt..."):
            final_result = await process_receipt(
                file_path, settings, client, db, push_confirmed=push
            )
        console.print(
            f"\n[bold]Final Result:[/bold]\n{json.dumps(final_result, indent=2, default=str)}"
        )


@app.command()
def reprocess(
    review_file: Path = typer.Argument(
        ..., help="Path to the review JSON file", exists=True
    ),
    push: bool = typer.Option(False, "--push", help="Actually write to Bexio"),
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

    asyncio.run(_process_interactive(orig_file, settings, push, dry_run))


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

    if not settings.bexio_push_enabled:
        console.print(
            "[yellow]⚠ Push gate: BEXIO_PUSH_ENABLED=false — receipts will queue for manual review.[/yellow]"
        )

    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def verify_token():
    """Verify connectivity to Bexio API (Read-only)."""
    settings = get_settings()
    setup_logging(settings.env)

    async def _run():
        async with BexioClient(
            token=settings.bexio_api_token,
            base_url=settings.bexio_base_url,
        ) as client:
            console.print(
                Panel("[bold blue]Bexio Connectivity Preflight (Read-only)[/bold blue]")
            )

            # 1. User Profile
            try:
                profile = await client.client.get("/3.0/users/me")
                profile.raise_for_status()
                user = profile.json()
                console.print(
                    f"✅ [bold]Authenticated User:[/bold] {user.get('firstname')} {user.get('lastname')} (ID: {user.get('id')})"
                )
            except Exception as e:
                console.print(f"❌ [bold red]User Profile Check Failed:[/bold red] {e}")

            # 2. Company Profile
            try:
                comp = await client.client.get("/2.0/company_profile")
                comp.raise_for_status()
                company = comp.json()

                # Handle cases where Bexio returns a list of profiles
                if isinstance(company, list) and len(company) > 0:
                    company = company[0]

                name = company.get("name") if isinstance(company, dict) else "Unknown"
                owner_id = (
                    company.get("owner_id") if isinstance(company, dict) else "Unknown"
                )

                console.print(
                    f"✅ [bold]Company Name:[/bold] {name} (Owner ID: {owner_id})"
                )
            except Exception as e:
                console.print(
                    f"❌ [bold red]Company Profile Check Failed:[/bold red] {e}"
                )

            # 3. Taxes
            try:
                taxes_resp = await client.client.get("/3.0/taxes")
                taxes_resp.raise_for_status()
                taxes = taxes_resp.json()
                console.print(f"✅ [bold]Tax Rates:[/bold] {len(taxes)} rates found")
            except Exception as e:
                console.print(f"❌ [bold red]Taxes Check Failed:[/bold red] {e}")

            # 4. Accounts
            try:
                accounts_resp = await client.client.get("/2.0/accounts")
                accounts_resp.raise_for_status()
                accounts = accounts_resp.json()
                console.print(
                    f"✅ [bold]Accounts:[/bold] {len(accounts)} accounts found"
                )
            except Exception as e:
                console.print(f"❌ [bold red]Accounts Check Failed:[/bold red] {e}")

            console.print("\n" + "─" * 40)
            if settings.bexio_push_enabled:
                console.print(
                    "[bold green]🟢 Push gate: BEXIO_PUSH_ENABLED=true — writes ENABLED.[/bold green]"
                )
            else:
                console.print(
                    "[bold yellow]⚠ Push gate: BEXIO_PUSH_ENABLED=false — no writes possible.[/bold yellow]"
                )
            console.print(
                "[dim]No writes were performed during this verification.[/dim]\n"
            )

    asyncio.run(_run())


@watch_app.command("folder")
def watch_folder(path: Path | None = typer.Option(None, help="Path to monitor")):
    """Monitor a folder for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)

    if not settings.bexio_push_enabled:
        console.print(
            "[yellow]⚠ Push gate: BEXIO_PUSH_ENABLED=false — receipts will queue for manual review.[/yellow]"
        )

    from .watcher import watch_folder as _watch

    asyncio.run(_watch(str(path or settings.inbox_path), settings))


@watch_app.command("gdrive")
def watch_gdrive(
    folder_id: str | None = typer.Option(None, help="Override Google Drive folder ID"),
):
    """Monitor Google Drive for new receipts."""
    settings = get_settings()
    setup_logging(settings.env)

    if not settings.bexio_push_enabled:
        console.print(
            "[yellow]⚠ Push gate: BEXIO_PUSH_ENABLED=false — receipts will queue for manual review.[/yellow]"
        )

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


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    path: Path | None = typer.Option(None, help="Path to monitor"),
):
    """Start both the dashboard and the folder watcher concurrently."""
    import uvicorn

    from .server import app as fastapi_app
    from .watcher import watch_folder as _watch

    settings = get_settings()
    setup_logging(settings.env)

    if not settings.bexio_push_enabled:
        console.print(
            "[yellow]⚠ Push gate: BEXIO_PUSH_ENABLED=false — receipts will queue for manual review.[/yellow]"
        )

    async def _start_all():
        config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        watcher_task = asyncio.create_task(
            _watch(str(path or settings.inbox_path), settings)
        )
        server_task = asyncio.create_task(server.serve())

        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(watcher_task, server_task)

    asyncio.run(_start_all())


def main():
    app()


if __name__ == "__main__":
    main()
