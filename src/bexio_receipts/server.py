import json
import mimetypes
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Form, Depends, status, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Gauge
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import functools
import sqlite3
import structlog

from fastapi.staticfiles import StaticFiles

from .config import Settings
from .bexio_client import BexioClient
from .models import Receipt
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

app = FastAPI(title="bexio-receipts Review Dashboard")


@functools.lru_cache()
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

# Setup templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


def get_db(settings: Settings = Depends(get_settings)):
    db = DuplicateDetector(settings.database_path)
    try:
        yield db
    finally:
        db.close()


security = HTTPBasic()


def verify_credentials(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
):
    is_correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"), settings.review_username.encode("utf8")
    )
    is_correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"), settings.review_password.encode("utf8")
    )

    if not (is_correct_username and is_correct_password):
        # Apply rate limiting manually on auth failure (brute-force protection)
        from limits import parse

        limit = parse("5/minute")
        if not limiter.limiter.hit(limit, get_remote_address(request)):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


RECEIPTS_PROCESSED = Gauge(
    "receipts_processed_total", "Total number of receipts processed"
)
RECEIPTS_FAILED = Gauge(
    "receipts_failed_total", "Total number of receipts sent to review"
)
OCR_CONFIDENCE = Gauge("ocr_confidence_avg", "Average OCR confidence of receipts")


@app.get("/metrics")
async def metrics(
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
    db: DuplicateDetector = Depends(get_db),
):
    """Prometheus metrics endpoint."""

    # Update metrics from DB/filesystem on the fly
    stats = db.get_stats()
    RECEIPTS_PROCESSED.set(stats["total_processed"])
    OCR_CONFIDENCE.set(stats["ocr_confidence_avg"])

    review_dir = Path(settings.review_dir)
    review_count = 0
    if review_dir.exists():
        review_count = len(list(review_dir.glob("*.json")))
    RECEIPTS_FAILED.set(review_count)

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz(settings: Settings = Depends(get_settings)):
    """Health check endpoint."""
    status_data = {
        "status": "ok",
        "db": "unknown",
        "bexio": "unknown",
        "imap": "not_configured",
        "gdrive": "not_configured",
    }

    # Check DB
    try:
        with sqlite3.connect(settings.database_path, timeout=5.0) as conn:
            conn.execute("SELECT 1").fetchone()
        status_data["db"] = "ok"
    except Exception as e:
        status_data["db"] = f"error: {e}"
        status_data["status"] = "error"
        logger.error("Health check DB error", error=str(e))

    # Check Bexio
    try:
        async with BexioClient(
            settings.bexio_api_token, settings.bexio_base_url, settings.default_vat_rate
        ) as bexio:
            resp = await bexio.client.get("/2.0/company_profile")
            resp.raise_for_status()
        status_data["bexio"] = "ok"
    except Exception as e:
        status_data["bexio"] = f"error: {e}"
        status_data["status"] = "error"
        logger.error("Health check Bexio error", error=str(e))

    # Check IMAP configured
    if settings.imap_server and settings.imap_user:
        status_data["imap"] = "configured"

    # Check GDrive configured
    if settings.gdrive_credentials_file:
        status_data["gdrive"] = "configured"

    status_code = (
        status.HTTP_200_OK
        if status_data["status"] == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=status_data)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """List all receipts awaiting review."""
    # Auto-redirect to setup if not configured
    if not settings.bexio_api_token or settings.bexio_api_token == "your_bexio_token":
        return RedirectResponse(url="/setup")

    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    reviews = []
    for p in review_dir.glob("*.json"):
        with open(p) as f:
            data = json.load(f)
            extracted = data.get("extracted", {}) or {}
            reviews.append(
                {
                    "id": p.stem,
                    "file": data.get("original_file"),
                    "errors": data.get("errors", []),
                    "merchant": extracted.get("merchant_name", "Unknown"),
                    "total": extracted.get("total_incl_vat", 0.0),
                    "date": extracted.get("transaction_date", "Unknown"),
                    "ocr_confidence": data.get("ocr_confidence"),
                    "failed_stage": data.get("failed_stage", "unknown"),
                }
            )

    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe()
    csrf_token = request.session["csrf_token"]

    success_msg = request.session.pop("success_msg", None)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"reviews": reviews, "csrf_token": csrf_token, "success_msg": success_msg},
    )


@app.get("/thumbnail/{review_id}")
async def get_receipt_thumbnail(
    review_id: str,
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Serve a thumbnail of the original receipt image."""
    review_dir = Path(settings.review_dir)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)
        img_path = data.get("original_file")

    if not img_path or not Path(img_path).exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    # Simple thumbnail generation using Pillow
    from PIL import Image
    import io

    try:
        with Image.open(img_path) as img:
            img.thumbnail((200, 200))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return Response(content=buf.getvalue(), media_type="image/jpeg")
    except Exception as e:
        logger.error("Thumbnail generation failed", error=str(e))
        return FileResponse(img_path)  # Fallback to original image


@app.get("/stats", response_class=HTMLResponse)
async def stats_view(
    request: Request,
    username: str = Depends(verify_credentials),
    db: DuplicateDetector = Depends(get_db),
):
    """Show processing statistics."""
    stats = db.get_stats()
    return templates.TemplateResponse(request, "stats.html", {"stats": stats})


@app.get("/review/{review_id}", response_class=HTMLResponse)
async def review_receipt(
    request: Request,
    review_id: str,
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Show review form for a specific receipt."""
    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)

    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe()

    csrf_token = request.session["csrf_token"]

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "id": review_id,
            "data": data,
            "receipt": data.get("extracted", {}),
            "csrf_token": csrf_token,
        },
    )


@app.get("/image/{review_id}")
async def get_receipt_image(
    review_id: str,
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Serve the original receipt image."""
    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)
        img_path = data.get("original_file")

    if not img_path or not Path(img_path).exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(img_path)


@app.post("/push/{review_id}")
async def push_to_bexio(
    request: Request,
    review_id: str,
    merchant_name: str = Form(...),
    date: str = Form(...),
    total_incl_vat: float = Form(...),
    vat_rate_pct: float | None = Form(None),
    csrf_token: str = Form(...),
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
    db: DuplicateDetector = Depends(get_db),
):
    """Update receipt data and push to bexio."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)

    # Update data from form
    receipt_data = data.get("extracted", {})
    receipt_data["merchant_name"] = merchant_name
    receipt_data["date"] = date
    receipt_data["total_incl_vat"] = total_incl_vat
    receipt_data["vat_rate_pct"] = vat_rate_pct

    # Re-validate via Pydantic (to ensure date/floats are correct)
    receipt = Receipt.model_validate(receipt_data)

    # Push to bexio
    img_path = data.get("original_file")
    filename = Path(img_path).name
    mime_type, _ = mimetypes.guess_type(img_path)
    mime_type = mime_type or "application/octet-stream"

    try:
        async with BexioClient(
            settings.bexio_api_token, settings.bexio_base_url, settings.default_vat_rate
        ) as bexio:
            await bexio.cache_lookups()
            file_uuid = await bexio.upload_file(img_path, filename, mime_type)

            # Prefer Bill if merchant exists
            if receipt.merchant_name:
                booking_account_id = settings.default_booking_account_id

                await bexio.create_purchase_bill(
                    receipt, file_uuid, booking_account_id=booking_account_id
                )
                # Save mapping
                db.set_merchant_account(receipt.merchant_name, booking_account_id)
            else:
                await bexio.create_expense(
                    receipt,
                    file_uuid,
                    booking_account_id=settings.default_booking_account_id,
                    bank_account_id=settings.default_bank_account_id,
                )

        # If successful, delete from review queue
        p.unlink()

        request.session["success_msg"] = f"✅ Successfully booked receipt from {receipt.merchant_name}."

        # Mark as processed in the database with financial stats
        file_hash = db.get_hash(img_path)
        # Note: the review JSON doesn't store OCR confidence, so we just pass None.
        db.mark_processed(
            file_hash,
            img_path,
            str(file_uuid),
            total_incl_vat=receipt.total_incl_vat,
            merchant_name=receipt.merchant_name,
            vat_amount=receipt.vat_amount,
        )

        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        logger.exception("Failed to push to bexio")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/discard/{review_id}")
async def discard_review(
    request: Request,
    review_id: str,
    csrf_token: str = Form(...),
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Remove a receipt from the review queue."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    review_dir = Path(settings.review_dir)
    p = review_dir / f"{review_id}.json"
    if p.exists():
        p.unlink()
    request.session["success_msg"] = "🗑️ Receipt discarded."
    return RedirectResponse(url="/", status_code=303)


@app.post("/bulk-discard")
async def bulk_discard_review(
    request: Request,
    ids: list[str] = Form([]),
    csrf_token: str = Form(...),
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Batch remove receipts from the review queue."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    review_dir = Path(settings.review_dir)
    count = 0
    for review_id in ids:
        p = review_dir / f"{review_id}.json"
        if p.exists():
            p.unlink()
            count += 1
    
    if count > 0:
        request.session["success_msg"] = f"🗑️ Discarded {count} receipts."
    return RedirectResponse(url="/", status_code=303)


@app.get("/setup", response_class=HTMLResponse)
async def setup_wizard(
    request: Request,
    username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Render the setup wizard page."""
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe()
    csrf_token = request.session["csrf_token"]
    return templates.TemplateResponse(
        request, "setup.html", {"settings": settings, "csrf_token": csrf_token}
    )


@app.get("/setup/check/bexio")
async def check_bexio_status(settings: Settings = Depends(get_settings)):
    try:
        async with BexioClient(
            settings.bexio_api_token, settings.bexio_base_url, settings.default_vat_rate
        ) as bexio:
            resp = await bexio.client.get("/2.0/company_profile")
            resp.raise_for_status()
            data = resp.json()
            return HTMLResponse(
                f'<span class="status-badge status-ok">OK ({data.get("name", "Connected")})</span>'
            )
    except Exception as e:
        msg = f"Error: {str(e)}"
        if "401" in msg:
            msg += ' <br><small>Tip: Check <a href="https://office.bexio.com/index.php/admin/apiTokens" target="_blank">Bexio API Tokens</a></small>'
        return HTMLResponse(f'<span class="status-badge status-error">{msg}</span>')


@app.get("/setup/check/ocr")
async def check_ocr_status(settings: Settings = Depends(get_settings)):
    if settings.ocr_engine == "paddleocr":
        try:
            import paddleocr

            return HTMLResponse(
                f'<span class="status-badge status-ok">OK (PaddleOCR {paddleocr.__version__})</span>'
            )
        except ImportError:
            return HTMLResponse(
                '<span class="status-badge status-error">Error: paddleocr not installed. <br>'
                '<small>Run: <code>uv add paddleocr paddlepaddle</code> '
                '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'uv add paddleocr paddlepaddle\')">Copy</button></small></span>'
            )
    elif settings.ocr_engine == "glm-ocr":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.glm_ocr_url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(
                    m == settings.glm_ocr_model
                    or m.startswith(f"{settings.glm_ocr_model}:")
                    for m in models
                ):
                    return HTMLResponse(
                        f'<span class="status-badge status-ok">OK (Model {settings.glm_ocr_model} loaded)</span>'
                    )
                else:
                    return HTMLResponse(
                        f'<span class="status-badge status-warning">Warning: Model {settings.glm_ocr_model} not found. <br>'
                        f'<small>Run: <code>ollama pull {settings.glm_ocr_model}</code> '
                        f'<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama pull {settings.glm_ocr_model}\')">Copy</button></small></span>'
                    )
        except Exception as e:
            return HTMLResponse(
                f'<span class="status-badge status-error">Error connecting to Ollama: {str(e)}. <br>'
                '<small>Run: <code>ollama serve</code> '
                '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama serve\')">Copy</button></small></span>'
            )
    return HTMLResponse('<span class="status-badge status-error">Unknown Engine</span>')


@app.get("/setup/check/llm")
async def check_llm_status(settings: Settings = Depends(get_settings)):
    if settings.llm_provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.ollama_url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(
                    m == settings.llm_model or m.startswith(f"{settings.llm_model}:")
                    for m in models
                ):
                    return HTMLResponse(
                        f'<span class="status-badge status-ok">OK (Model {settings.llm_model} loaded)</span>'
                    )
                else:
                    return HTMLResponse(
                        f'<span class="status-badge status-warning">Warning: Model {settings.llm_model} not found. <br>'
                        f'<small>Run: <code>ollama pull {settings.llm_model}</code> '
                        f'<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama pull {settings.llm_model}\')">Copy</button></small></span>'
                    )
        except Exception as e:
            return HTMLResponse(
                f'<span class="status-badge status-error">Error connecting to Ollama: {str(e)}. <br>'
                '<small>Run: <code>ollama serve</code> '
                '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama serve\')">Copy</button></small></span>'
            )
    elif settings.llm_provider == "openai":
        import os

        if os.getenv("OPENAI_API_KEY"):
            return HTMLResponse(
                '<span class="status-badge status-ok">OK (API Key set)</span>'
            )
        else:
            return HTMLResponse(
                '<span class="status-badge status-error">Error: OPENAI_API_KEY not set. <br><small>Add to .env or environment</small></span>'
            )
    return HTMLResponse(
        '<span class="status-badge status-error">Unknown Provider</span>'
    )


@app.get("/setup/check/system")
async def check_system_status():
    import shutil

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        return HTMLResponse(
            f'<span class="status-badge status-ok">OK ({pdftoppm})</span>'
        )
    else:
        return HTMLResponse(
            '<span class="status-badge status-error">Error: Poppler not found. <br>'
            '<small>Run: <code>sudo apt install poppler-utils</code> '
            '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'sudo apt install poppler-utils\')">Copy</button></small></span>'
        )


@app.get("/setup/check/db")
async def check_db_status(settings: Settings = Depends(get_settings)):
    try:
        db_path = Path(settings.database_path)
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return HTMLResponse(
            f'<span class="status-badge status-ok">OK ({db_path.name})</span>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<span class="status-badge status-error">Error: {str(e)}</span>'
        )


@app.post("/setup/pull-model")
async def pull_ollama_model(
    request: Request,
    model: str = Form(...),
    csrf_token: str = Form(...),
    settings: Settings = Depends(get_settings),
):
    """Trigger Ollama model pull."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    url = (
        settings.ollama_url
        if "ollama_url" in Settings.model_fields
        else settings.glm_ocr_url
    )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=None) as client:
            # We use stream=True but here we'll just wait for completion for simplicity in this MVP
            # A better version would use Server-Sent Events to show progress
            resp = await client.post(
                f"{url}/api/pull", json={"name": model}, timeout=None
            )
            resp.raise_for_status()
            return HTMLResponse(
                f'<div class="status-badge status-ok">Successfully pulled {model}</div>'
            )
    except Exception as e:
        return HTMLResponse(
            f'<div class="status-badge status-error">Failed to pull {model}: {str(e)}</div>'
        )


@app.get("/setup/run-all")
async def run_all_checks():
    """Hacky way to trigger all checks via HTMX by returning a trigger header."""
    # This tells HTMX to trigger these events on the client side
    return Response(headers={"HX-Trigger": "load-checks"})
