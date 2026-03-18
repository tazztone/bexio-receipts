# Refined bexio Receipt Pipeline — Implementation Plan

## What Changed vs. the Original Blueprint

After cross-referencing **PaddleOCR v5 docs**, **Pydantic AI docs**, and the **live bexio API spec**, here are the concrete issues found and improvements made:

> [!CAUTION]
> **Expense API payload was wrong.** The original plan used invented field names (`expense_date`, `net_total`, `gross_total`, `currency_id`, `file_ids`). The **actual** bexio `POST /4.0/expenses` payload uses `paid_on`, `amount`, `tax_id`, `booking_account_id`, `bank_account_id`, `attachment_ids` (UUID strings, not numeric). This would have silently failed in production.

> [!WARNING]
> **PaddleOCR API has changed.** The `PaddleOCR(lang='de')` constructor is outdated. PP-OCRv5 uses `ocr.predict(input=...)` and returns structured result objects with `.print()`, `.save_to_json()` etc. The `lang` parameter still works for legacy models but PP-OCRv5 handles multi-language natively.

> [!IMPORTANT]
> **Use Pydantic AI instead of raw OpenAI calls.** The `client.beta.chat.completions.parse()` approach works but is provider-locked. Pydantic AI's `Agent(model, output_type=Receipt)` gives the same structured output with a single line, works across OpenAI/Ollama/Anthropic, and adds retry/validation for free.

---

## Architecture (Unchanged — Still Correct)

```
Ingestion ──▶ OCR (PaddleOCR or GLM-OCR) ──▶ LLM Extraction (Pydantic AI) ──▶ Validation ──▶ bexio API
                                                                           │ fail
                                                                           ▼
                                                                     Review Queue
```

---

## Refined Steps

### Step 1: Project Scaffolding (NEW)

Set up a proper Python project with `uv`:

```bash
uv init --name bexio-receipts
uv add paddleocr pydantic-ai httpx python-dotenv pdf2image Pillow
uv add --dev pytest pytest-asyncio ruff
```

**Module layout:**
```
src/bexio_receipts/
├── __init__.py
├── config.py          # Settings via pydantic-settings (env vars)
├── ocr.py             # PaddleOCR wrapper
├── extraction.py      # Pydantic AI agent for receipt parsing
├── models.py          # Receipt / LineItem Pydantic models
├── validation.py      # Pure-Python business rules
├── bexio_client.py    # bexio API client (httpx async)
├── pipeline.py        # Orchestrator: ingest → ocr → extract → validate → push
└── cli.py             # CLI entrypoint (process a file/dir)
tests/
├── test_ocr.py
├── test_extraction.py
├── test_validation.py
├── test_bexio_client.py
└── fixtures/          # Sample receipt images + expected JSON
```

### Step 2: Authentication (Refined)

**No change to strategy** — PAT for personal use.

**Improvement:** Use `pydantic-settings` for configuration instead of raw `os.getenv()`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bexio_api_token: str
    bexio_base_url: str = "https://api.bexio.com"
    
    # OCR Settings
    ocr_engine: str = "paddleocr"  # Options: paddleocr, glm-ocr
    ocr_confidence_threshold: float = 0.85
    glm_ocr_model: str = "glm-ocr"
    glm_ocr_url: str = "http://localhost:11434"
    
    # LLM Settings
    llm_provider: str = "ollama"  # or "openai"
    llm_model: str = "qwen2.5:7b"
    
    model_config = {"env_file": ".env"}
```

### Step 3: OCR Layer (CORRECTED)

**What changed:** Support for multiple engines (PaddleOCR v5 and GLM-OCR via Ollama).

#### Option A: PaddleOCR (Default)
PP-OCRv5 handles multi-language natively.

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
    use_textline_orientation=True,
)
results = ocr.ocr(file_path)
```

#### Option B: GLM-OCR (NEW)
GLM-OCR (0.9B) is a multimodal LLM ideal for edge deployments. We use it via Ollama with the prompt `"Text Recognition:"`.

```python
async def run_glm_ocr(file_path: str, settings: Settings):
    # Base64 encode image and send to Ollama /api/chat
    # Prompt: "Text Recognition:"
    ...
```

**Key differences from original plan:**
- Unified `async_run_ocr` entry point to handle both sync (Paddle) and async (GLM) engines.
- PP-OCRv5 handles DE/FR/IT/EN natively.
- GLM-OCR provides a lightweight, highly accurate alternative for structured documents.

### Step 4: LLM Extraction (REWRITTEN — Use Pydantic AI)

**What changed:** Replaced raw OpenAI `client.beta.chat.completions.parse()` with `pydantic_ai.Agent`.

```python
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from typing import Optional
from datetime import date

class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total: float

class Receipt(BaseModel):
    merchant_name: str
    date: date
    currency: str = "CHF"
    subtotal_excl_vat: Optional[float] = None
    vat_rate_pct: Optional[float] = Field(None, description="Swiss VAT: 8.1, 2.6, 3.8, or 0.0")
    vat_amount: Optional[float] = None
    total_incl_vat: float
    line_items: Optional[list[LineItem]] = None
    invoice_number: Optional[str] = None
    payment_method: Optional[str] = None  # NEW: card/cash/twint etc.

# Ollama (local, private)
model = OpenAIChatModel(
    model_name="qwen2.5:7b",
    provider=OllamaProvider(base_url="http://localhost:11434/v1"),
)

agent = Agent(
    model,
    output_type=Receipt,
    instructions="""Extract receipt data from OCR text. Swiss VAT rates are:
    - 8.1% (standard), 2.6% (reduced — food, books), 3.8% (accommodation).
    Return null for fields not found. If multiple VAT rates appear, use the dominant one.""",
)

result = agent.run_sync(f"Receipt text:\n{raw_text}")
receipt: Receipt = result.output
```

**Why this is better:**
1. **Provider-agnostic**: swap Ollama ↔ OpenAI ↔ Anthropic by changing one line
2. **Built-in retries**: Pydantic AI retries on validation failure automatically
3. **`payment_method` field added**: useful for matching against bank statements later

### Step 5: Validation Layer (IMPROVED)

**What changed:** Handle Optional fields (many receipts don't show VAT breakdown), add more rules.

```python
from datetime import date, timedelta

VALID_CH_VAT = {0.0, 2.6, 3.8, 8.1}

def validate_receipt(r: Receipt) -> list[str]:
    errors = []
    
    # 1. Totals integrity (only if both values present)
    if r.subtotal_excl_vat is not None and r.vat_amount is not None:
        expected = r.subtotal_excl_vat + r.vat_amount
        if abs(expected - r.total_incl_vat) > 0.05:  # 5 Rappen tolerance (Swiss rounding)
            errors.append(f"Total mismatch: {r.subtotal_excl_vat} + {r.vat_amount} ≠ {r.total_incl_vat}")
    
    # 2. VAT rate check (only if extracted)
    if r.vat_rate_pct is not None and r.vat_rate_pct not in VALID_CH_VAT:
        errors.append(f"Invalid Swiss VAT rate: {r.vat_rate_pct}%")
    
    # 3. VAT back-calculation check
    if r.vat_rate_pct and r.subtotal_excl_vat and r.vat_amount:
        expected_vat = round(r.subtotal_excl_vat * r.vat_rate_pct / 100, 2)
        if abs(expected_vat - r.vat_amount) > 0.05:
            errors.append(f"VAT amount doesn't match rate: {r.vat_rate_pct}% of {r.subtotal_excl_vat} ≠ {r.vat_amount}")
    
    # 4. Date sanity
    if r.date > date.today():
        errors.append(f"Future date: {r.date}")
    if r.date < date.today() - timedelta(days=365):
        errors.append(f"Receipt older than 1 year: {r.date}")
    
    # 5. Amount sanity
    if r.total_incl_vat <= 0:
        errors.append("Total must be positive")
    if r.total_incl_vat > 10_000:
        errors.append(f"Unusually large amount: {r.total_incl_vat} CHF — manual review")
    
    # 6. Line items cross-check (NEW)
    if r.line_items:
        items_total = sum(i.total for i in r.line_items)
        if r.subtotal_excl_vat and abs(items_total - r.subtotal_excl_vat) > 0.10:
            errors.append(f"Line items sum ({items_total}) ≠ subtotal ({r.subtotal_excl_vat})")
    
    return errors
```

**Improvements over original:**
- **5 Rappen tolerance** (Swiss rounding to nearest 0.05 CHF)
- **Optional-aware**: doesn't crash when VAT fields are missing
- **VAT back-calculation**: catches rate/amount mismatches
- **Age check**: receipts >1 year old are flagged
- **Large amount warning**: >10k CHF triggers manual review
- **Line-item cross-check**: sum of items vs subtotal

### Step 6: bexio API Client (CORRECTED)

**What changed:** Fixed to match the **actual** bexio API payload:

```python
import httpx
from uuid import UUID

class BexioClient:
    def __init__(self, token: str, base_url: str = "https://api.bexio.com"):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0,
        )
        self._tax_cache: dict[float, int] = {}
        self._account_cache: dict[str, int] = {}
    
    async def cache_lookups(self):
        """Fetch and cache tenant-specific IDs at startup."""
        # Tax rates
        taxes = (await self.client.get("/3.0/taxes")).json()
        for t in taxes:
            if t.get("value"):
                self._tax_cache[float(t["value"])] = t["id"]
        
        # Accounts (for booking_account_id)
        accounts = (await self.client.get("/2.0/accounts")).json()
        for a in accounts:
            self._account_cache[a["account_no"]] = a["id"]
    
    async def upload_file(self, file_path: str, filename: str, mime_type: str) -> str:
        """Upload file, returns UUID string (not int!)."""
        with open(file_path, "rb") as f:
            resp = await self.client.post(
                "/3.0/files",
                files={"file": (filename, f, mime_type)},
            )
            resp.raise_for_status()
            return resp.json()["id"]  # UUID string
    
    async def create_expense(self, receipt: "Receipt", file_uuid: str, 
                              booking_account_id: int, bank_account_id: int) -> dict:
        """Create expense with CORRECT field names."""
        payload = {
            "title": receipt.merchant_name,
            "paid_on": receipt.date.isoformat(),         # NOT "expense_date"
            "currency_code": receipt.currency,            # NOT "currency_id"
            "amount": round(receipt.total_incl_vat, 2),   # NOT "gross_total"
            "tax_id": self._tax_cache.get(receipt.vat_rate_pct, self._tax_cache.get(8.1)),
            "booking_account_id": booking_account_id,     # Required!
            "bank_account_id": bank_account_id,           # Required!
            "attachment_ids": [file_uuid],                # UUID strings in a list
        }
        
        # Optional supplier
        if receipt.merchant_name:
            payload["address"] = {"lastname_company": receipt.merchant_name, "type": "COMPANY"}
        
        resp = await self.client.post("/4.0/expenses", json=payload)
        resp.raise_for_status()
        return resp.json()
```

**Critical corrections:**
| Original Plan (❌ wrong) | Actual API (✅ correct) |
|---|---|
| `expense_date` | `paid_on` |
| `currency_id: 1` | `currency_code: "CHF"` |
| `net_total` | N/A — only `amount` exists |
| `gross_total` | `amount` |
| `file_ids: [int]` | `attachment_ids: [UUID string]` |
| No `booking_account_id` | **Required field** |
| No `bank_account_id` | **Required field** |

### Step 7: Pipeline Orchestrator (NEW)

```python
async def process_receipt(file_path: str, settings: Settings, bexio: BexioClient):
    """Full pipeline: OCR → Extract → Validate → Push."""
    # 1. OCR
    raw_text, avg_confidence, ocr_lines = run_ocr(file_path)
    
    if avg_confidence < settings.ocr_confidence_threshold:
        return await send_to_review(file_path, raw_text, ["Low OCR confidence: {avg_confidence:.1%}"])
    
    # 2. LLM extraction
    receipt = await extract_receipt(raw_text, settings)
    
    # 3. Validation
    errors = validate_receipt(receipt)
    if errors:
        return await send_to_review(file_path, raw_text, errors, receipt)
    
    # 4. Push to bexio
    file_uuid = await bexio.upload_file(file_path, Path(file_path).name, guess_mime(file_path))
    expense = await bexio.create_expense(
        receipt, file_uuid,
        booking_account_id=settings.default_booking_account_id,
        bank_account_id=settings.default_bank_account_id,
    )
    
    return {"status": "booked", "expense_id": expense["id"], "receipt": receipt}
```

### Step 8: Review Queue (SIMPLIFIED)

For MVP, use a **JSON file queue** instead of a full web UI:

```python
import json
from pathlib import Path

REVIEW_DIR = Path("./review_queue")

async def send_to_review(file_path: str, raw_text: str, errors: list[str], receipt=None):
    REVIEW_DIR.mkdir(exist_ok=True)
    review_file = REVIEW_DIR / f"{Path(file_path).stem}.json"
    review_file.write_text(json.dumps({
        "original_file": file_path,
        "ocr_text": raw_text,
        "errors": errors,
        "extracted": receipt.model_dump(mode="json") if receipt else None,
    }, indent=2, default=str))
    return {"status": "review", "review_file": str(review_file)}
```

A proper FastAPI/htmx review UI can be Phase 2 once the core pipeline works.

---

## Swiss-Specific Gotchas (Kept + Expanded)

| Issue | Detail |
|---|---|
| **VAT codes are tenant-specific** | Fetch via `GET /3.0/taxes` per company. Never hardcode IDs |
| **Bezugssteuer (reverse charge)** | Requires specific account + VAT code combo |
| **Rounding** | Swiss cash payments round to nearest 5 Rappen. Allow ±0.05 CHF tolerance |
| **Multi-VAT receipts** | Supermarket receipts mix 2.6% (food) and 8.1% (non-food). Phase 1: use dominant rate. Phase 2: split line items |
| **`booking_account_id` is required** | The API rejects expenses without it. Default to a general expense account |
| **`bank_account_id` is required** | The API rejects expenses without it. Map to user's default payment method |
| **Draft → Done flow** | Create as draft, then `POST /4.0/expenses/{id}/actions` with `{"action": "done"}` to finalize |
| **Immutable once done** | Must revert to draft before editing |
| **Rate limit** | Respect `RateLimit-Reset` header. Use `httpx` with retry middleware |

---

## Recommended Stack (UPDATED)

| Layer | Tool | Change from Original |
|---|---|---|
| **Package management** | `uv` | NEW — user preference |
| OCR | PaddleOCR or GLM-OCR | Added GLM-OCR support |
| **LLM** | Pydantic AI + Ollama/OpenAI | Replaced raw OpenAI calls |
| **Schema** | Pydantic v2 | Unchanged |
| **Business rules** | Pure Python | Enhanced with Swiss rounding |
| **HTTP client** | `httpx` (async) | Unchanged |
| **Config** | `pydantic-settings` | NEW — typed env vars |
| **Auth** | PAT (personal) | Unchanged |
| **Review** | JSON queue → FastAPI Phase 2 | Simplified for MVP |

---

## Phased Delivery

### Phase 1: Core Pipeline (THIS SPRINT)
- [ ] Project scaffold with `uv`
- [ ] OCR module with confidence tracking
- [ ] LLM extraction via Pydantic AI
- [ ] Validation layer with Swiss rules
- [ ] bexio client with correct API fields
- [ ] CLI: `bexio-receipt process <file>`
- [ ] Tests with fixture receipts

### Phase 2: Production Hardening
- [ ] FastAPI review UI with htmx
- [ ] Email inbox watcher (IMAP)
- [ ] Folder watcher (watchdog)
- [ ] Multi-VAT receipt splitting
- [ ] Duplicate detection (hash-based)
- [ ] Structured logging (logfire?)

### Phase 3: Nice-to-Have
- [ ] Telegram bot ingestion
- [ ] Merchant name → bexio contact auto-matching
- [ ] Dashboard / stats page
- [ ] Auto-categorization (expense type → account mapping)

---

## Verification Plan

### Automated Tests
```bash
uv run pytest tests/ -v
```

Key test cases:
1. **`test_validation.py`** — Pure unit tests with known receipt data (totals, VAT rates, edge cases)
2. **`test_extraction.py`** — Mock LLM responses, verify Pydantic model parsing
3. **`test_bexio_client.py`** — Mock httpx responses, verify correct payload field names
4. **`test_ocr.py`** — Integration test with a sample receipt image in `tests/fixtures/`

### Manual Verification
1. Process a real Swiss receipt (Coop/Migros) end-to-end with `--dry-run` flag
2. Verify the generated bexio payload matches the actual API schema
3. Create one test expense in bexio sandbox and confirm it appears in the UI
