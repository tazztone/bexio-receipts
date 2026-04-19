"""
Dashboard backend powered by FastAPI and HTMX.
Provides the web interface for receipt review and management.
"""

import functools
import json
import mimetypes
import re
import secrets
import sqlite3
from pathlib import Path

import bcrypt
import structlog
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from .bexio_client import BexioClient
from .config import Settings
from .database import DuplicateDetector
from .models import Receipt

logger = structlog.get_logger(__name__)

app = FastAPI(title="bexio-receipts Review Dashboard")


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

# Setup templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _custom_rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> Response:
    return _rate_limit_exceeded_handler(request, exc)


def get_db(settings: Settings = Depends(get_settings)):
    db = DuplicateDetector(settings.database_path)
    try:
        yield db
    finally:
        db.close()


security = HTTPBasic(auto_error=False)


def verify_credentials(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
):
    if settings.review_skip_auth:
        return "admin"

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_users = settings.review_users or {
        settings.review_username: settings.review_password
    }

    is_authorized = False
    for username, password_hash in valid_users.items():
        if secrets.compare_digest(
            credentials.username.encode("utf8"), username.encode("utf8")
        ) and bcrypt.checkpw(
            credentials.password.encode("utf8"), password_hash.encode("utf8")
        ):
            is_authorized = True
            break

    if not is_authorized:
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
    _username: str = Depends(verify_credentials),
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
async def healthz(_settings: Settings = Depends(get_settings)):
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
        with sqlite3.connect(_settings.database_path, timeout=5.0) as conn:
            conn.execute("SELECT 1").fetchone()
        status_data["db"] = "ok"
    except Exception as e:
        status_data["db"] = f"error: {e}"
        status_data["status"] = "error"
        logger.error("Health check DB error", error=str(e))

    # Check Bexio
    try:
        async with BexioClient(
            _settings.bexio_api_token,
            _settings.bexio_base_url,
            _settings.default_vat_rate,
            _settings.default_payment_terms_days,
        ) as bexio:
            resp = await bexio.client.get("/2.0/company_profile")
            resp.raise_for_status()
        status_data["bexio"] = "ok"
    except Exception as e:
        status_data["bexio"] = f"error: {e}"
        status_data["status"] = "error"
        logger.error("Health check Bexio error", error=str(e))

    # Check IMAP configured
    if _settings.imap_server and _settings.imap_user:
        status_data["imap"] = "configured"

    # Check GDrive configured
    if _settings.gdrive_credentials_file:
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
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
    page: int = 1,
    per_page: int = 50,
    search: str | None = None,
):
    """List all receipts awaiting review."""
    # Auto-redirect to setup if not configured
    if not settings.bexio_api_token or settings.bexio_api_token == "your_bexio_token":
        return RedirectResponse(url="/setup")

    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)

    # Sort files by creation time, newest first
    all_files_list = sorted(
        review_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True
    )

    reviews_data = []
    for p in all_files_list:
        with open(p) as f:
            data = json.load(f)
            extracted = data.get("extracted", {}) or {}
            merchant = extracted.get("merchant_name", "Unknown")

            if search and search.lower() not in merchant.lower():
                continue

            reviews_data.append({
                "id": p.stem,
                "file": data.get("original_file"),
                "errors": data.get("errors", []),
                "merchant": merchant,
                "total": extracted.get("total_incl_vat", 0.0),
                "date": extracted.get("transaction_date", "Unknown"),
                "ocr_confidence": data.get("ocr_confidence"),
                "failed_stage": data.get("failed_stage", "unknown"),
            })

    total_reviews = len(reviews_data)
    total_pages = max(1, (total_reviews + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    reviews_page = reviews_data[start_idx:end_idx]

    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe()
    csrf_token = request.session["csrf_token"]

    success_msg = request.session.pop("success_msg", None)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "reviews": reviews_page,
            "csrf_token": csrf_token,
            "success_msg": success_msg,
            "page": page,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "search": search,
        },
    )


@app.get("/thumbnail/{review_id}")
async def get_receipt_thumbnail(
    review_id: str,
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Serve a thumbnail of the original receipt image."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review_dir = Path(settings.review_dir)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)
        img_path = data.get("original_file")

    if not img_path or not Path(img_path).exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    # Canonicalization check
    img_path_obj = Path(img_path).resolve()
    allowed_roots = [
        Path(settings.inbox_path).resolve(),
        Path(settings.review_dir).resolve(),
    ]
    if not any(img_path_obj.is_relative_to(root) for root in allowed_roots):
        logger.warning(
            "Access denied: Path is outside allowed roots",
            path=str(img_path_obj),
            allowed_roots=[str(r) for r in allowed_roots],
        )
        raise HTTPException(status_code=403, detail="Access denied")

    # Simple thumbnail generation using Pillow
    import io

    from PIL import Image

    try:
        with Image.open(img_path) as img:
            img.thumbnail((200, 200))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return Response(content=buf.getvalue(), media_type="image/jpeg")
    except Exception as e:
        logger.error("Thumbnail generation failed", error=str(e))
        return FileResponse(img_path)  # Fallback to original image


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve a dummy favicon to prevent 404 logs."""
    return Response(content=b"", media_type="image/x-icon")


@app.post("/bulk-action")
async def bulk_action(
    request: Request,
    ids: list[str] = Form([]),
    action: str = Form(...),
    csrf_token: str = Form(...),
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
    db: DuplicateDetector = Depends(get_db),
):
    """Process or discard multiple receipts."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not ids:
        request.session["success_msg"] = "⚠️ No receipts selected for bulk action."
        return RedirectResponse(url="/", status_code=303)

    review_dir = Path(settings.review_dir)
    success_count = 0
    error_count = 0

    if action == "discard":
        for review_id in ids:
            p = review_dir / f"{review_id}.json"
            if p.exists():
                p.unlink()
                success_count += 1
        request.session["success_msg"] = f"🗑️ Discarded {success_count} receipts."

    elif action == "process":
        if not settings.bexio_push_enabled:
            request.session["success_msg"] = (
                "⚠️ Bulk push blocked: BEXIO_PUSH_ENABLED=false. Enable it in .env to push multiple receipts."
            )
            return RedirectResponse(url="/", status_code=303)

        async with BexioClient(
            settings.bexio_api_token,
            settings.bexio_base_url,
            settings.default_vat_rate,
            settings.default_payment_terms_days,
            push_enabled=settings.bexio_push_enabled,
        ) as bexio:
            await bexio.cache_lookups()

            for review_id in ids:
                p = review_dir / f"{review_id}.json"
                if not p.exists():
                    continue

                try:
                    with open(p) as f:
                        data = json.load(f)

                    extracted = data.get("extracted", {})
                    receipt = Receipt.model_validate(extracted)
                    img_path = data.get("original_file")
                    filename = Path(img_path).name
                    mime_type, _ = mimetypes.guess_type(img_path)
                    mime_type = mime_type or "application/octet-stream"

                    file_uuid = await bexio.upload_file(img_path, filename, mime_type)

                    # Use merchant-specific account or default
                    booking_account_id = None
                    if receipt.merchant_name:
                        booking_account_id = db.get_merchant_account(
                            receipt.merchant_name
                        )

                    if not booking_account_id:
                        booking_account_id = settings.default_booking_account_id

                    if receipt.merchant_name:
                        await bexio.create_purchase_bill(
                            receipt, file_uuid, booking_account_id=booking_account_id
                        )
                    else:
                        await bexio.create_expense(
                            receipt,
                            file_uuid,
                            booking_account_id=booking_account_id,
                            bank_account_id=settings.default_bank_account_id,
                        )

                    p.unlink()

                    file_hash = db.get_hash(img_path)
                    db.mark_processed(
                        file_hash,
                        img_path,
                        str(file_uuid),
                        total_incl_vat=receipt.total_incl_vat,
                        merchant_name=receipt.merchant_name,
                        vat_amount=receipt.vat_amount,
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(
                        "Bulk process failed for item", id=review_id, error=str(e)
                    )
                    error_count += 1

        msg = f"✅ Processed {success_count} receipts."
        if error_count > 0:
            msg += f" (⚠️ {error_count} failed)"
        request.session["success_msg"] = msg

    return RedirectResponse(url="/", status_code=303)


@app.get("/history", response_class=HTMLResponse)
async def get_history(
    request: Request,
    page: int = 1,
    search: str | None = None,
    _username: str = Depends(verify_credentials),
    _settings: Settings = Depends(get_settings),
    db: DuplicateDetector = Depends(get_db),
):
    """Browse history of processed receipts."""
    limit = 25
    offset = (page - 1) * limit
    receipts = db.get_processed_receipts(limit=limit, offset=offset, search=search)
    total_count = db.get_total_processed_count(search=search)
    total_pages = (total_count + limit - 1) // limit

    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "receipts": receipts,
            "page": page,
            "total_pages": total_pages,
            "search": search,
            "total_count": total_count,
        },
    )


@app.get("/stats", response_class=HTMLResponse)
async def stats_view(
    request: Request,
    _username: str = Depends(verify_credentials),
    db: DuplicateDetector = Depends(get_db),
):
    """Show processing statistics."""
    stats = db.get_stats()
    return templates.TemplateResponse(request, "stats.html", {"stats": stats})


@app.get("/review/{review_id}", response_class=HTMLResponse)
async def get_review_form(
    request: Request,
    review_id: str,
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Show review form for a specific receipt."""
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    p = review_dir / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")

    with open(p) as f:
        data = json.load(f)

    # Fetch accounts for the dropdown
    async with BexioClient(
        settings.bexio_api_token,
        settings.bexio_base_url,
        settings.default_vat_rate,
        settings.default_payment_terms_days,
    ) as bexio:
        all_accounts = await bexio.get_accounts()

    # Resolve allowed SOLL accounts to internal IDs
    allowed_numbers = {str(no) for no in settings.bexio_allowed_soll_accounts}
    allowed_accounts = [
        {"id": a["id"], "account_no": a["account_no"], "name": a["name"]}
        for a in all_accounts
        if str(a.get("account_no")) in allowed_numbers
    ]

    # Resolve HABEN accounts
    haben_bank_id = next(
        (
            a["id"]
            for a in all_accounts
            if str(a.get("account_no")) == str(settings.bexio_haben_account_bank)
        ),
        None,
    )
    haben_cash_id = next(
        (
            a["id"]
            for a in all_accounts
            if str(a.get("account_no")) == str(settings.bexio_haben_account_cash)
        ),
        None,
    )

    # Detect bexio_action
    receipt_data = data.get("extracted", {})
    vat_breakdown = receipt_data.get("vat_breakdown", [])
    merchant_name = receipt_data.get("merchant_name")

    # Rule: multi-rate OR merchant present -> purchase_bill
    if merchant_name or (vat_breakdown and len(vat_breakdown) > 1):
        bexio_action = "purchase_bill"
    else:
        bexio_action = "expense"

    # Bug #3 Guard: Degrade to purchase_bill if HABEN accounts are missing
    if bexio_action == "expense" and (haben_bank_id is None or haben_cash_id is None):
        logger.warning(
            "HABEN accounts not found in chart of accounts; degrading to purchase_bill",
            bank=settings.bexio_haben_account_bank,
            cash=settings.bexio_haben_account_cash,
        )
        bexio_action = "purchase_bill"

    # Get the default account for this merchant if known
    db = DuplicateDetector(settings.database_path)
    default_account_id = None
    if merchant_name:
        default_account_id = db.get_merchant_account(merchant_name)

    if not default_account_id:
        default_account_id = settings.default_booking_account_id

    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe()

    csrf_token = request.session["csrf_token"]

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "id": review_id,
            "data": data,
            "receipt": receipt_data,
            "allowed_accounts": allowed_accounts,
            "default_account_id": default_account_id,
            "haben_bank_id": haben_bank_id,
            "haben_cash_id": haben_cash_id,
            "bexio_action": bexio_action,
            "csrf_token": csrf_token,
            "payment_method": receipt_data.get("payment_method"),
        },
    )


@app.get("/image/{review_id}")
async def get_receipt_image(
    review_id: str,
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Serve the original receipt image."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")

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

    # Canonicalization check
    img_path_obj = Path(img_path).resolve()
    allowed_roots = [
        Path(settings.inbox_path).resolve(),
        Path(settings.review_dir).resolve(),
    ]
    if not any(img_path_obj.is_relative_to(root) for root in allowed_roots):
        logger.warning(
            "Access denied: Path is outside allowed roots",
            path=str(img_path_obj),
            allowed_roots=[str(r) for r in allowed_roots],
        )
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(img_path)


@app.post("/push/{review_id}")
async def push_to_bexio(
    request: Request,
    review_id: str,
    merchant_name: str = Form(...),
    date: str = Form(...),
    total_incl_vat: float = Form(...),
    vat_rate_pct: float | None = Form(None),
    booking_account_ids: list[int] = Form(...),
    bank_account_id: int | None = Form(None),
    bexio_action: str = Form("purchase_bill"),
    csrf_token: str = Form(...),
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
    db: DuplicateDetector = Depends(get_db),
):
    """Update receipt data and push to bexio."""
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")

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

    # Re-validate via Pydantic
    receipt = Receipt.model_validate(receipt_data)

    # Validation Guard for account count
    vat_breakdown = receipt.vat_breakdown
    expected_count = len(vat_breakdown) if vat_breakdown else 1
    if len(booking_account_ids) != expected_count:
        raise HTTPException(
            status_code=422,
            detail=f"Account count mismatch: expected {expected_count}, got {len(booking_account_ids)}",
        )

    # Push to bexio
    img_path = data.get("original_file")
    filename = Path(img_path).name
    mime_type, _ = mimetypes.guess_type(img_path)
    mime_type = mime_type or "application/octet-stream"

    if not settings.bexio_push_enabled:
        raise HTTPException(
            status_code=403,
            detail="Bexio push gate is closed (BEXIO_PUSH_ENABLED=false).",
        )

    try:
        async with BexioClient(
            settings.bexio_api_token,
            settings.bexio_base_url,
            settings.default_vat_rate,
            settings.default_payment_terms_days,
            push_enabled=settings.bexio_push_enabled,
        ) as bexio:
            await bexio.cache_lookups()
            file_uuid = await bexio.upload_file(img_path, filename, mime_type)

            # Logic #4: Server-side override (never trust client blindly)
            if bexio_action == "expense":
                if receipt.merchant_name or (vat_breakdown and len(vat_breakdown) > 1):
                    logger.info("Overriding 'expense' to 'purchase_bill' for safety")
                    bexio_action = "purchase_bill"

            # Routing decision
            if bexio_action == "purchase_bill":
                # Always Purchase Bill for multi-rate or merchant
                await bexio.create_purchase_bill(
                    receipt, file_uuid, booking_account_ids=booking_account_ids
                )
                # Save first account mapping for merchant
                if receipt.merchant_name:
                    db.set_merchant_account(
                        receipt.merchant_name, booking_account_ids[0]
                    )
            else:
                # Single-rate expense
                await bexio.create_expense(
                    receipt,
                    file_uuid,
                    booking_account_id=booking_account_ids[0],
                    bank_account_id=bank_account_id or settings.default_bank_account_id,
                )

        # Success: delete review file
        p.unlink()

        request.session["success_msg"] = (
            f"✅ Successfully booked receipt from {receipt.merchant_name or 'Unknown'}."
        )

        file_hash = db.get_hash(img_path)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/discard/{review_id}")
async def discard_review(
    request: Request,
    review_id: str,
    csrf_token: str = Form(...),
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Remove a receipt from the review queue."""
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")

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
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Batch remove receipts from the review queue."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    import re

    review_dir = Path(settings.review_dir)
    count = 0
    for review_id in ids:
        if not re.match(r"^[a-zA-Z0-9_-]+$", review_id):
            continue
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
    _username: str = Depends(verify_credentials),
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
async def check_bexio_status(
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    try:
        async with BexioClient(
            settings.bexio_api_token,
            settings.bexio_base_url,
            settings.default_vat_rate,
            settings.default_payment_terms_days,
        ) as bexio:
            resp = await bexio.client.get("/2.0/company_profile")
            resp.raise_for_status()
            data = resp.json()

            # Handle case where Bexio returns a list of profiles
            company_data = data
            if isinstance(data, list) and len(data) > 0:
                company_data = data[0]

            name = (
                company_data.get("name", "Connected")
                if isinstance(company_data, dict)
                else "Connected"
            )

            return HTMLResponse(
                f'<span class="status-badge status-ok">OK ({name})</span>'
            )
    except Exception as e:
        msg = f"Error: {e!s}"
        if "401" in msg:
            msg += ' <br><small>Tip: Check <a href="https://office.bexio.com/index.php/admin/apiTokens" target="_blank">Bexio API Tokens</a></small>'
        return HTMLResponse(f'<span class="status-badge status-error">{msg}</span>')


@app.get("/setup/check/ocr")
async def check_ocr_status(
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
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
                    f"<small>Run: <code>ollama pull {settings.glm_ocr_model}</code> "
                    f'<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama pull {settings.glm_ocr_model}\')">Copy</button></small></span>'
                )
    except Exception as e:
        return HTMLResponse(
            f'<span class="status-badge status-error">Error connecting to Ollama: {e!s}. <br>'
            "<small>Run: <code>ollama serve</code> "
            '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama serve\')">Copy</button></small></span>'
        )


@app.get("/setup/check/llm")
async def check_llm_status(
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
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
                        f"<small>Run: <code>ollama pull {settings.llm_model}</code> "
                        f'<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'ollama pull {settings.llm_model}\')">Copy</button></small></span>'
                    )
        except Exception as e:
            return HTMLResponse(
                f'<span class="status-badge status-error">Error connecting to Ollama: {e!s}. <br>'
                "<small>Run: <code>ollama serve</code> "
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
async def check_system_status(_username: str = Depends(verify_credentials)):
    import shutil

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        return HTMLResponse(
            f'<span class="status-badge status-ok">OK ({pdftoppm})</span>'
        )
    else:
        return HTMLResponse(
            '<span class="status-badge status-error">Error: Poppler not found. <br>'
            "<small>Run: <code>sudo apt install poppler-utils</code> "
            '<button class="outline secondary" style="padding: 0 0.2rem; font-size: 0.6rem;" onclick="navigator.clipboard.writeText(\'sudo apt install poppler-utils\')">Copy</button></small></span>'
        )


@app.get("/setup/check/db")
async def check_db_status(
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    try:
        db_path = Path(settings.database_path)
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return HTMLResponse(
            f'<span class="status-badge status-ok">OK ({db_path.name})</span>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<span class="status-badge status-error">Error: {e!s}</span>'
        )


@app.post("/setup/pull-model")
async def pull_ollama_model(
    request: Request,
    model: str = Form(...),
    csrf_token: str = Form(...),
    _username: str = Depends(verify_credentials),
    settings: Settings = Depends(get_settings),
):
    """Trigger Ollama model pull."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not re.match(r"^[a-zA-Z0-9._:-]+$", model):
        raise HTTPException(status_code=400, detail="Invalid model name")

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
            f'<div class="status-badge status-error">Failed to pull {model}: {e!s}</div>'
        )


@app.get("/setup/run-all")
async def run_all_checks(_username: str = Depends(verify_credentials)):
    """Hacky way to trigger all checks via HTMX by returning a trigger header."""
    # This tells HTMX to trigger these events on the client side
    return Response(headers={"HX-Trigger": "load-checks"})
