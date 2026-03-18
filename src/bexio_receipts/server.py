import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import structlog

from .config import Settings
from .bexio_client import BexioClient
from .models import Receipt
from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

app = FastAPI(title="bexio-receipts Review Dashboard")
settings = Settings()
db = DuplicateDetector(settings.database_path)

# Setup templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

REVIEW_DIR = Path(settings.review_dir)
REVIEW_DIR.mkdir(exist_ok=True, parents=True)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """List all receipts awaiting review."""
    reviews = []
    for p in REVIEW_DIR.glob("*.json"):
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
async def stats_view(request: Request):
    """Show processing statistics."""
    stats = db.get_stats()
    return templates.TemplateResponse("stats.html", {"request": request, "stats": stats})

@app.get("/review/{review_id}", response_class=HTMLResponse)
async def review_receipt(request: Request, review_id: str):
    """Show review form for a specific receipt."""
    p = REVIEW_DIR / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Review not found")
    
    with open(p) as f:
        data = json.load(f)
    
    return templates.TemplateResponse("review.html", {
        "request": request, 
        "id": review_id, 
        "data": data,
        "receipt": data.get("extracted", {})
    })

@app.get("/image/{review_id}")
async def get_receipt_image(review_id: str):
    """Serve the original receipt image."""
    p = REVIEW_DIR / f"{review_id}.json"
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
    review_id: str,
    merchant_name: str = Form(...),
    date: str = Form(...),
    total_incl_vat: float = Form(...),
    vat_rate_pct: float | None = Form(None),
):
    """Update receipt data and push to bexio."""
    p = REVIEW_DIR / f"{review_id}.json"
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
    
    try:
        async with BexioClient(settings.bexio_api_token, settings.bexio_base_url) as bexio:
            await bexio.cache_lookups()
            file_uuid = await bexio.upload_file(img_path, filename, "image/png")
            
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
        return RedirectResponse(url="/", status_code=303)
        
    except Exception as e:
        logger.exception("Failed to push to bexio")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/discard/{review_id}")
async def discard_review(review_id: str):
    """Remove a receipt from the review queue."""
    p = REVIEW_DIR / f"{review_id}.json"
    if p.exists():
        p.unlink()
    return RedirectResponse(url="/", status_code=303)
