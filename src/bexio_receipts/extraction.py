"""
Logic for extracting structured receipt data from OCR text using Pydantic AI.
"""

import re
from typing import Literal

import httpx
import structlog
from dateutil import parser
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import (
    OpenAIJsonSchemaTransformer,
    OpenAIModelProfile,
)
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .models import (
    IntermediateReceipt,
    RawReceipt,
    RawVatRow,
    RawVatRows,
    Receipt,
    VatEntry,
)

logger = structlog.get_logger(__name__)


class AccountAssignment(BaseModel):
    vat_rate: float  # 2.6 or 8.1
    account_id: str  # "4200"
    account_name: str  # "Einkauf Handelsware"
    confidence: Literal["high", "medium", "low"]
    reasoning: str  # one sentence — for review queue visibility


class AccountAssignments(BaseModel):
    """Wrapper for list[AccountAssignment] as pydantic-ai doesn't support bare lists for some models."""

    assignments: list[AccountAssignment]


class ExtractionTrace(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    ocr_text: str = ""
    step1_output: dict | None = None  # intermediate.model_dump()
    step1_vat_raw: str = ""
    step2_vat_cleaned: str = ""
    step2_output: list[dict] = []  # [r.model_dump() for r in vat_rows]
    resolved_rows: list[dict] = []  # [e.model_dump() for e in vat_entries]
    step3_assignments: list[dict] = []  # [a.model_dump() for a in assignments]
    error_stage: str = ""
    error_detail: str = ""


STRIP_LINES = re.compile(
    r"^(Total|Rundungsdifferenz|Endbetrag|Summe|Zusammenfassung|Sie sparen|MWST exkl|MWST inkl|Netto|<thead>|<tbody>|<tfoot>|<tr>|<th>)\b",
    re.IGNORECASE | re.MULTILINE,
)


def validate_vat_snippet(snippet: str) -> str | None:
    """Returns error string if snippet is malformed, None if valid."""
    # Pass-through for structured HTML/Markdown tables from OCR Pass 2
    if ("<table" in snippet.lower() and "</table>" in snippet.lower()) or (
        "|" in snippet and snippet.count("|") >= 4
    ):
        # Minimum check: table must contain at least one numeric value to be valid
        if re.search(r"\d+[.,]\d+", snippet):
            return None
        return "Table present but contains no numeric values"

    number = re.compile(r"\d+[.,]\d+")
    if not any(len(number.findall(line)) >= 2 for line in snippet.splitlines()):
        return (
            f"No line has 2+ numeric tokens — likely vertical extraction: {snippet!r}"
        )
    return None


def clean_vat_snippet(snippet: str) -> str:
    """Deterministically strip summary and header lines from the VAT snippet."""
    # If it's an HTML table, don't strip lines yet; the LLM handles it better whole
    if "<table" in snippet.lower():
        return snippet.strip()

    lines = [
        line for line in snippet.splitlines() if not STRIP_LINES.match(line.strip())
    ]
    return "\n".join(lines).strip()


def resolve_vat_rows(rows: list[RawVatRow]) -> list[VatEntry]:
    rate_match_tol = 0.02  # IEEE 754 safe; false-positives rejected by math check below
    math_tol = 0.02  # covers rounding on all Swiss receipt formats

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
                # Primary check: VAT + Base = Total
                if abs(round(base + vat, 2) - total) < math_tol:
                    # Secondary check: Base * Rate ≈ VAT (must match within tolerance)
                    if base > 0 and abs(round(base * rate / 100, 2) - vat) < math_tol:
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


def _build_model(
    settings: Settings, client: httpx.AsyncClient
) -> tuple[OpenAIChatModel, httpx.AsyncClient | AsyncOpenAI | None]:
    """Helper to build the pydantic-ai model consistently."""
    or_client = None
    if settings.llm_provider == "ollama":
        from pydantic_ai.providers.ollama import OllamaProvider

        base_url = settings.ollama_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        model = OpenAIChatModel(
            model_name=settings.llm_model,
            provider=OllamaProvider(base_url=base_url, http_client=client),
        )
    elif settings.llm_provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider

        model = OpenAIChatModel(
            model_name=settings.llm_model,
            provider=OpenAIProvider(http_client=client),
        )
    elif settings.llm_provider == "openrouter":
        from openai import AsyncOpenAI
        from pydantic_ai.providers.openai import OpenAIProvider

        api_key = settings.openrouter_api_key
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required for OpenRouter provider")

        # or_client isn't actually an httpx.AsyncClient but it has a .close()
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
    return model, or_client


class ExtractionError(Exception):
    """Custom exception that carries the trace for debugging."""

    def __init__(self, message: str, trace: ExtractionTrace | None = None):
        super().__init__(message)
        self.trace = trace


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
) -> tuple[Receipt, ExtractionTrace]:
    """
    Extract receipt data from OCR text using a Two-Step LLM Pipeline.
    """
    trace = ExtractionTrace(ocr_text=raw_text)
    # or_client must be closed by the caller; see finally block below.
    model, or_client = _build_model(settings, client)
    try:
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
                "3. TOTAL: Extract the grand total in CHF only. IGNORE any currency conversion lines "
                "(e.g. 'EUR ... zum Kurs ...'). The CHF total is labeled 'Total Rechnung', 'Ihr Betrag', "
                "or 'Endbetrag'.\n"
                "4. CURRENCY: Always 'CHF' unless no CHF total exists at all.\n"
                "5. VAT TABLE RAW: Find the Markdown table that summarizes VAT "
                "(Zusammenfassung gem. MWST, MwSt-Übersicht) containing the rates "
                "(8.1%, 2.6%). COPY that table verbatim as Markdown (with | pipes). "
                "IGNORE the line item table."
            ),
        )

        logger.info("Step 1: Preliminary extraction started", model=settings.llm_model)
        res1 = await searcher_agent.run(f"Receipt text:\n{raw_text}")
        intermediate = res1.output
        if not isinstance(intermediate, IntermediateReceipt):
            trace.error_stage = "step1"
            trace.error_detail = "Unexpected output type from Step 1"
            raise ExtractionError(trace.error_detail, trace=trace)

        trace.step1_output = intermediate.model_dump()
        trace.step1_vat_raw = intermediate.vat_table_raw or ""
        logger.debug("Step1 output", intermediate=trace.step1_output)

        # STEP 2: VAT Parsing (Assigner)
        vat_rows = []
        if intermediate.vat_table_raw and len(intermediate.vat_table_raw.strip()) > 5:
            # Pre-Step 2 Guard
            validation_error = validate_vat_snippet(intermediate.vat_table_raw)
            if validation_error:
                logger.warning(
                    "Step 1 produced invalid VAT snippet, retrying",
                    error=validation_error,
                )
                trace.error_stage = "step1_vat_validation"
                trace.error_detail = validation_error
                raise ExtractionError(validation_error, trace=trace)

            parser_agent = Agent(
                model,
                output_type=RawVatRows,
                retries=1,
                system_prompt=(
                    "You are a VAT data entry specialist. I will give you a tiny snippet of a VAT table "
                    "(may be plain text, Markdown, or HTML <table>).\n"
                    "Extract the rows. For each row:\n"
                    "- rate: e.g. 2.6, 8.1\n"
                    "- col_a, col_b, col_c: the numbers in that row in order from left to right.\n"
                    "RULES:\n"
                    "1. If HTML, extract the numeric values from the <td> tags in each <tr>.\n"
                    "2. rate: MUST be one of [8.1, 7.7, 2.6, 3.8, 2.5]. IGNORE any other numbers.\n"
                    "3. IGNORE summary rows (Total, Summe, Rundung).\n"
                    "4. IGNORE columns containing savings values.\n"
                    "5. ONLY extract rows representing a specific VAT rate."
                ),
            )

            cleaned_snippet = clean_vat_snippet(intermediate.vat_table_raw)
            trace.error_stage = ""  # clear any previous stage error if retrying
            trace.step2_vat_cleaned = cleaned_snippet
            logger.info("Step 2: VAT parsing started", snippet=cleaned_snippet)
            logger.debug("Step2 cleaned_snippet", snippet=cleaned_snippet)

            res2 = await parser_agent.run(f"VAT Table Snippet:\n{cleaned_snippet}")
            vat_rows = res2.output.rows
            if not isinstance(vat_rows, list):
                trace.error_stage = "step2"
                trace.error_detail = "Unexpected output type from Step 2"
                raise ExtractionError(trace.error_detail, trace=trace)

            trace.step2_output = [r.model_dump() for r in vat_rows]
            logger.debug("Step2 resolved_rows", rows=trace.step2_output)

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
            trace.resolved_rows = [e.model_dump() for e in receipt.vat_breakdown]
            return receipt, trace
        except ValueError as ve:
            trace.error_stage = "assembly"
            trace.error_detail = str(ve)
            raise ExtractionError(f"VAT assembly failed: {ve!s}", trace=trace) from ve
    finally:
        if or_client is not None:
            await or_client.close() if hasattr(or_client, 'close') else await or_client.aclose()


async def classify_accounts(
    receipt: Receipt,
    raw_text: str,
    settings: Settings,
    client: httpx.AsyncClient,
    trace: ExtractionTrace,
) -> list[AccountAssignment]:
    """
    Step 3: Assign Swiss booking accounts based on full OCR context and VAT rates.
    """
    # or_client must be closed by the caller; see finally block below.
    model, or_client = _build_model(settings, client)
    try:
        accounts_context = "\n".join([
            f"- {acc_id}: {desc}" for acc_id, desc in settings.bexio_accounts.items()
        ])

        classifier_agent = Agent(
            model,
            output_type=AccountAssignments,
            retries=1,
            system_prompt=(
                "You are a Swiss bookkeeper. Given a receipt's OCR text and extracted data, "
                "assign the correct booking account number for each VAT entry found.\n"
                "### AVAILABLE ACCOUNTS ###\n"
                f"{accounts_context}\n\n"
                "### RULES ###\n"
                "1. Use product descriptions and categories in the OCR text to determine the account.\n"
                "2. Food/resale goods → 4200. Non-food consumables → 4201. Services → 4400. "
                "Waste/disposal → 6460. Fees/Surcharges → 4270.\n"
                "3. If the receipt mixes categories, assign per VAT rate based on which products "
                "fall under that rate.\n"
                "4. If uncertain, default to 4200 and set confidence='low'.\n"
                "5. IMPORTANT: Swiss VAT rate 2.6% is almost always food (4200). 8.1% is non-food/services (4201/4400)."
            ),
        )

        receipt_summary = receipt.model_dump_json()
        logger.info(
            "Step 3: Account classification started", merchant=receipt.merchant_name
        )
        res = await classifier_agent.run(
            f"Receipt Summary:\n{receipt_summary}\n\nFull OCR Text:\n{raw_text}"
        )
        return res.output.assignments
    except Exception as e:
        logger.error("Step 3: Account classification failed", error=str(e))
        trace.error_stage = "step3"
        trace.error_detail = str(e)
        return []
    finally:
        if or_client is not None:
            await or_client.close() if hasattr(or_client, 'close') else await or_client.aclose()
