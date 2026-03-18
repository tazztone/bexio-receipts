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
from fastapi import status

import sqlite3
import structlog

from .config import Settings
from .bexio_client import BexioClient
from .models import Receipt
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

app = FastAPI(title="bexio-receipts Review Dashboard")

def get_settings() -> Settings:
    return Settings()

app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

def get_db(settings: Settings = Depends(get_settings)) -> DuplicateDetector:
    return DuplicateDetector(settings.database_path)

# Setup templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

security = HTTPBasic()

def verify_credentials(request: Request, credentials: HTTPBasicCredentials = Depends(security), settings: Settings = Depends(get_settings)):
    is_correct_username = secrets.compare_digest(credentials.username.encode("utf8"), b"admin")
    is_correct_password = secrets.compare_digest(credentials.password.encode("utf8"), settings.review_password.encode("utf8"))

    if not (is_correct_username and is_correct_password):
        # Apply rate limiting manually on auth failure (brute-force protection)
        from limits import parse
        limit = parse("5/minute")
        if not limiter.limiter.hit(limit, get_remote_address(request)):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

RECEIPTS_PROCESSED = Gauge('receipts_processed_total', 'Total number of receipts processed')
RECEIPTS_FAILED = Gauge('receipts_failed_total', 'Total number of receipts sent to review')
OCR_CONFIDENCE = Gauge('ocr_confidence_avg', 'Average OCR confidence of receipts')

@app.get("/metrics")
async def metrics(settings: Settings = Depends(get_settings), db: DuplicateDetector = Depends(get_db)):
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
    status_data = {"status": "ok", "db": "unknown", "bexio": "unknown", "imap": "not_configured", "gdrive": "not_configured"}

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
        async with BexioClient(settings.bexio_api_token, settings.bexio_base_url) as bexio:
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

    status_code = status.HTTP_200_OK if status_data["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=status_data)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(verify_credentials), settings: Settings = Depends(get_settings)):
    """List all receipts awaiting review."""
    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    reviews = []
    for p in review_dir.glob("*.json"):
        with open(p) as f:
            data = json.load(f)
            reviews.append({
                "id": p.stem,
                "file": data.get("original_file"),
                "errors": data.get("errors", []),
                "merchant": data.get("extracted", {}).get("merchant_name", "Unknown"),
                "total": data.get("extracted", {}).get("total_incl_vat", 0.0),
            })
    
    return templates.TemplateResponse("dashboard.html", {"request": request, "reviews": reviews})

@app.get("/stats", response_class=HTMLResponse)
async def stats_view(request: Request, username: str = Depends(verify_credentials), db: DuplicateDetector = Depends(get_db)):
    """Show processing statistics."""
    stats = db.get_stats()
    return templates.TemplateResponse("stats.html", {"request": request, "stats": stats})

@app.get("/review/{review_id}", response_class=HTMLResponse)
async def review_receipt(request: Request, review_id: str, username: str = Depends(verify_credentials), settings: Settings = Depends(get_settings)):
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

    return templates.TemplateResponse("review.html", {
        "request": request, 
        "id": review_id, 
        "data": data,
        "receipt": data.get("extracted", {}),
        "csrf_token": csrf_token
    })

@app.get("/image/{review_id}")
async def get_receipt_image(review_id: str, username: str = Depends(verify_credentials), settings: Settings = Depends(get_settings)):
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
    db: DuplicateDetector = Depends(get_db)
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
    receipt = Receipt(**receipt_data)
    
    # Push to bexio
    img_path = data.get("original_file")
    filename = Path(img_path).name
    mime_type, _ = mimetypes.guess_type(img_path)
    mime_type = mime_type or "application/octet-stream"
    
    try:
        async with BexioClient(settings.bexio_api_token, settings.bexio_base_url, settings.default_vat_rate) as bexio:
            await bexio.cache_lookups()
            file_uuid = await bexio.upload_file(img_path, filename, mime_type)
            
            # Prefer Bill if merchant exists
            if receipt.merchant_name:
                booking_account_id = settings.default_booking_account_id
                
                await bexio.create_purchase_bill(
                    receipt, file_uuid,
                    booking_account_id=booking_account_id
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

        # Mark as processed in the database with financial stats
        file_hash = db.get_hash(img_path)
        # Note: the review JSON doesn't store OCR confidence, so we just pass None.
        db.mark_processed(
            file_hash,
            img_path,
            str(file_uuid),
            total_incl_vat=receipt.total_incl_vat,
            merchant_name=receipt.merchant_name,
            vat_amount=receipt.vat_amount
        )

        return RedirectResponse(url="/", status_code=303)
        
    except Exception as e:
        logger.exception("Failed to push to bexio")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/discard/{review_id}")
async def discard_review(request: Request, review_id: str, csrf_token: str = Form(...), username: str = Depends(verify_credentials), settings: Settings = Depends(get_settings)):
    """Remove a receipt from the review queue."""
    if not csrf_token or request.session.get("csrf_token") != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    review_dir = Path(settings.review_dir)
    review_dir.mkdir(exist_ok=True, parents=True)
    p = review_dir / f"{review_id}.json"
    if p.exists():
        p.unlink()
    return RedirectResponse(url="/", status_code=303)
