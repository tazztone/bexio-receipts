import httpx
import structlog
from typing import Optional, List, Dict
from .models import Receipt

logger = structlog.get_logger(__name__)

class BexioClient:
    def __init__(self, token: str, base_url: str = "https://api.bexio.com"):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0,
        )
        self._tax_cache: Dict[float, int] = {}
        self._account_cache: Dict[str, int] = {}
    
    async def cache_lookups(self):
        """Fetch and cache tenant-specific IDs at startup."""
        # Tax rates
        resp = await self.client.get("/3.0/taxes")
        resp.raise_for_status()
        taxes = resp.json()
        for t in taxes:
            if t.get("value") is not None:
                self._tax_cache[float(t["value"])] = t["id"]
        
        # Accounts (for booking_account_id)
        # Note: 2.0/accounts might be paginated or large, but for now this is the strategy
        resp = await self.client.get("/2.0/accounts")
        resp.raise_for_status()
        accounts = resp.json()
        for a in accounts:
            if "account_no" in a:
                self._account_cache[str(a["account_no"])] = a["id"]
    
    async def upload_file(self, file_path: str, filename: str, mime_type: str) -> str:
        """Upload file, returns UUID string."""
        with open(file_path, "rb") as f:
            resp = await self.client.post(
                "/3.0/files",
                files={"file": (filename, f, mime_type)},
            )
            resp.raise_for_status()
            return resp.json()["id"]  # UUID string
    
    async def create_expense(self, receipt: Receipt, file_uuid: str, 
                              booking_account_id: int, bank_account_id: int) -> Dict:
        """Create expense with CORRECT field names."""
        if receipt.vat_breakdown and len(receipt.vat_breakdown) > 1:
            logger.warning(
                "Multiple VAT rates detected, but bexio Expenses only support one tax_id. "
                "Using dominant rate.",
                breakdown=receipt.vat_breakdown
            )

        payload = {
            "title": receipt.merchant_name,
            "paid_on": receipt.date.isoformat(),
            "currency_code": receipt.currency,
            "amount": round(receipt.total_incl_vat, 2),
            "tax_id": self._tax_cache.get(receipt.vat_rate_pct, self._tax_cache.get(8.1)),
            "booking_account_id": booking_account_id,
            "bank_account_id": bank_account_id,
            "attachment_ids": [file_uuid],
        }
        
        # Optional supplier info if needed
        if receipt.merchant_name:
            payload["address"] = {"lastname_company": receipt.merchant_name, "type": "COMPANY"}
        
        resp = await self.client.post("/4.0/expenses", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.client.aclose()
