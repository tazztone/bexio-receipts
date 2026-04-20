"""
Logic for extracting structured receipt data from OCR text using Pydantic AI.
"""

import re

import httpx
import structlog
from dateutil import parser
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import (
    OpenAIJsonSchemaTransformer,
    OpenAIModelProfile,
)
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .models import IntermediateReceipt, RawReceipt, RawVatRow, Receipt, VatEntry

logger = structlog.get_logger(__name__)

STRIP_LINES = re.compile(
    r"^(Total|Rundungsdifferenz|Endbetrag|Summe|Zusammenfassung|Sie sparen|MWST exkl|MWST inkl|Netto)\b",
    re.IGNORECASE | re.MULTILINE,
)


def clean_vat_snippet(snippet: str) -> str:
    """Deterministically strip summary and header lines from the VAT snippet."""
    lines = [
        line for line in snippet.splitlines() if not STRIP_LINES.match(line.strip())
    ]
    return "\n".join(lines).strip()


def resolve_vat_rows(rows: list[RawVatRow]) -> list[VatEntry]:
    rate_match_tol = 0.01  # rate is a label; must match exactly
    math_tol = 0.05  # covers rounding on all Swiss receipt formats

    entries = []
    for row in rows:
        rate = row.rate
        a, b, c = row.col_a, row.col_b, row.col_c
        resolved = False

        # Strategy 1: Rate column detection (Prodega style)
        # One column equals the rate value itself; remaining two are (vat, base).
        if c is not None:
            for rate_col, x, y in [(a, b, c), (b, a, c), (c, a, b)]:
                if abs(rate_col - rate) < rate_match_tol:
                    # Determine which of (x, y) is VAT and which is base
                    for vat, base in [(x, y), (y, x)]:
                        if (
                            base > 0
                            and abs(round(base * rate / 100, 2) - vat) < math_tol
                        ):
                            entries.append(
                                VatEntry(rate=rate, vat_amount=vat, base_amount=base)
                            )
                            resolved = True
                            break
                if resolved:
                    break

        if resolved:
            continue

        # Strategy 2: Default additive check (VAT + Base = Total)
        candidates: list[tuple[float, float, float | None]] = []
        if c is not None:
            candidates = [
                (a, b, c),
                (a, c, b),
                (b, a, c),
                (b, c, a),
                (c, a, b),
                (c, b, a),
            ]
        else:
            candidates = [(a, b, None), (b, a, None)]

        for vat, base, total in candidates:
            if total is not None:
                if abs(round(base + vat, 2) - total) < math_tol:
                    entries.append(
                        VatEntry(
                            rate=rate,
                            vat_amount=vat,
                            base_amount=base,
                            total_incl_vat=total,
                        )
                    )
                    resolved = True
                    break
            else:
                # If only two columns, we must rely on rate math
                if base > 0 and abs(round(base * rate / 100, 2) - vat) < math_tol:
                    entries.append(
                        VatEntry(rate=rate, vat_amount=vat, base_amount=base)
                    )
                    resolved = True
                    break

        if not resolved:
            logger.warning("Skipping unresolvable VAT row", row=row.model_dump())
            continue

    if rows and not entries:
        raise ValueError(
            "LLM extracted VAT rows but none could be resolved mathematically"
        )

    return entries


def assemble_receipt(raw: RawReceipt) -> Receipt:
    vat_entries = resolve_vat_rows(raw.vat_rows)

    total_incl_vat = raw.total_incl_vat
    if total_incl_vat is None and vat_entries:
        # Note: back-calculated total may differ by ±Rundungsdifferenz (typ. 0.01)
        total_incl_vat = round(
            sum(e.base_amount + e.vat_amount for e in vat_entries), 2
        )
        logger.info("Computed total_incl_vat from VAT breakdown", total=total_incl_vat)

    # Populate dominant VAT rate and aggregates
    vat_rate_pct = None
    sum_vat = 0.0
    sum_base = 0.0
    if vat_entries:
        # Sort by total_incl_vat descending to pick dominant rate
        sorted_entries = sorted(
            vat_entries,
            key=lambda e: (
                e.total_incl_vat
                if e.total_incl_vat is not None
                else (e.base_amount + e.vat_amount)
            ),
            reverse=True,
        )
        vat_rate_pct = sorted_entries[0].rate
        sum_vat = round(sum(e.vat_amount for e in vat_entries), 2)
        sum_base = round(sum(e.base_amount for e in vat_entries), 2)

    parsed_date = None
    if raw.transaction_date:
        try:
            parsed_date = parser.parse(raw.transaction_date, dayfirst=True).date()
        except Exception as e:
            logger.warning(
                "Could not parse date", raw_date=raw.transaction_date, error=str(e)
            )

    return Receipt(
        merchant_name=raw.merchant_name,
        transaction_date=parsed_date,
        currency=raw.currency or "CHF",
        total_incl_vat=total_incl_vat,
        vat_rate_pct=vat_rate_pct,
        vat_amount=sum_vat if vat_entries else None,
        subtotal_excl_vat=sum_base if vat_entries else None,
        vat_breakdown=vat_entries,
        payment_method=raw.payment_method,
    )


def _is_rate_limit(exc: BaseException) -> bool:
    """Detect 429s regardless of which exception type wraps them."""
    return "429" in str(exc) or "rate" in str(exc).lower()


class ExtractionError(Exception):
    """Custom exception that carries the raw model response for debugging."""

    def __init__(self, message: str, last_raw: str | None = None):
        super().__init__(message)
        self.last_raw = last_raw


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=(
        retry_if_exception_type((
            httpx.HTTPStatusError,
            ValidationError,
            ExtractionError,
        ))
        | retry_if_exception(_is_rate_limit)
    ),
    reraise=True,
)
async def extract_receipt(
    raw_text: str, settings: Settings, client: httpx.AsyncClient
) -> tuple[Receipt, str | None]:
    """
    Extract receipt data from OCR text using a Two-Step LLM Pipeline.
    """
    or_client = None
    try:
        if settings.llm_provider == "ollama":
            base_url = settings.ollama_url.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"

            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OllamaProvider(base_url=base_url, http_client=client),
            )
        elif settings.llm_provider == "openai":
            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OpenAIProvider(http_client=client),
            )
        elif settings.llm_provider == "openrouter":
            from openai import AsyncOpenAI

            api_key = settings.openrouter_api_key
            if not api_key:
                raise ValueError(
                    "OPENROUTER_API_KEY is required for OpenRouter provider"
                )

            or_client = AsyncOpenAI(
                base_url=settings.openrouter_url,
                api_key=api_key,
                default_headers={
                    "HTTP-Referer": settings.openrouter_site_url,
                    "X-Title": settings.openrouter_site_name,
                },
            )
            model = OpenAIChatModel(
                model_name=settings.llm_model,
                provider=OpenAIProvider(openai_client=or_client),
                profile=OpenAIModelProfile(
                    supports_json_schema_output=True,
                    supports_json_object_output=True,
                    json_schema_transformer=OpenAIJsonSchemaTransformer,
                ),
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")

        # STEP 1: Preliminary Extraction (Searcher)
        searcher_agent = Agent(
            model,
            output_type=IntermediateReceipt,
            retries=1,
            system_prompt=(
                "Transcribe basic receipt data and locate the VAT table.\n"
                "### RULES ###\n"
                "1. MERCHANT: Extract vendor name. IGNORE customer addresses.\n"
                "2. DATE: Transcribe exactly (e.g. 31.01.2026).\n"
                "3. TOTAL: Extract grand total amount.\n"
                "4. VAT TABLE RAW: Find the VAT summary section (usually at the bottom). "
                "Copy-paste the lines of that table VERBATIM. Do not process or reformat it."
            ),
        )

        logger.info("Step 1: Preliminary extraction started", model=settings.llm_model)
        res1 = await searcher_agent.run(f"Receipt text:\n{raw_text}")
        intermediate = res1.output
        if not isinstance(intermediate, IntermediateReceipt):
            raise ExtractionError("Step 1 failed: Unexpected output type")

        # STEP 2: VAT Parsing (Assigner)
        vat_rows = []
        if intermediate.vat_table_raw and len(intermediate.vat_table_raw.strip()) > 5:
            parser_agent = Agent(
                model,
                output_type=list[RawVatRow],
                retries=1,
                system_prompt=(
                    "You are a VAT data entry specialist. I will give you a tiny snippet of a VAT table.\n"
                    "Extract the rows. For each row:\n"
                    "- rate: e.g. 2.6, 8.1\n"
                    "- col_a, col_b, col_c: the numbers in that row in order from left to right.\n"
                    "RULES:\n"
                    "1. IGNORE summary rows (Total, Summe, Rundung).\n"
                    "2. IGNORE columns containing savings values or VAT codes (1, 2).\n"
                    "3. ONLY extract rows representing a specific VAT rate."
                ),
            )

            cleaned_snippet = clean_vat_snippet(intermediate.vat_table_raw)
            logger.info("Step 2: VAT parsing started", snippet=cleaned_snippet)
            res2 = await parser_agent.run(f"VAT Table Snippet:\n{cleaned_snippet}")
            vat_rows = res2.output
            if not isinstance(vat_rows, list):
                raise ExtractionError("Step 2 failed: Unexpected output type")

        # Final assembly
        raw_receipt = RawReceipt(
            merchant_name=intermediate.merchant_name,
            transaction_date=intermediate.transaction_date,
            currency=intermediate.currency,
            total_incl_vat=intermediate.total_incl_vat,
            vat_rows=vat_rows,
            payment_method=intermediate.payment_method,
        )

        try:
            receipt = assemble_receipt(raw_receipt)
            # Capture raw text for debugging
            last_raw = f"Step1: {res1.output}\n\nStep2: {vat_rows if 'res2' in locals() else 'N/A'}"
            return receipt, last_raw
        except ValueError as ve:
            raise ExtractionError(
                f"VAT assembly failed: {ve!s}", last_raw=str(intermediate)
            ) from ve
    finally:
        if or_client is not None:
            await or_client.close()
