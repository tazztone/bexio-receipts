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
        resp = await self.client.get("/2.0/accounts")
        resp.raise_for_status()
        accounts = resp.json()
        for a in accounts:
            if "account_no" in a:
                self._account_cache[str(a["account_no"])] = a["id"]
    
    async def get_tax_id(self, rate: Optional[float]) -> int:
        """Return bexio tax ID for a given rate, fallback to standard (8.1)."""
        if rate is None:
            return self._tax_cache.get(8.1, 1) # Fallback to standard
        return self._tax_cache.get(float(rate), self._tax_cache.get(8.1, 1))

    async def upload_file(self, file_path: str, filename: str, mime_type: str) -> str:
        """Upload file, returns UUID string."""
        with open(file_path, "rb") as f:
            resp = await self.client.post(
                "/3.0/files",
                files={"file": (filename, f, mime_type)},
            )
            resp.raise_for_status()
            return resp.json()["id"]  # UUID string

    async def find_or_create_contact(self, name: str) -> int:
        """Search for a contact by name, create if not found."""
        # Search
        search_payload = [
            {"field": "name_1", "value": name, "criteria": "="}
        ]
        resp = await self.client.post("/2.0/contact/search", json=search_payload)
        resp.raise_for_status()
        results = resp.json()
        
        if results:
            return results[0]["id"]
            
        # Create
        create_payload = {
            "contact_type_id": 1, # Company
            "name_1": name,
            "user_id": 1, # Default user
            "owner_id": 1,
        }
        resp = await self.client.post("/2.0/contact", json=create_payload)
        resp.raise_for_status()
        return resp.json()["id"]

    async def create_expense(self, receipt: Receipt, file_uuid: str, 
                              booking_account_id: int, bank_account_id: int) -> Dict:
        """Create a simple expense (bexio v4)."""
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
            "tax_id": await self.get_tax_id(receipt.vat_rate_pct),
            "booking_account_id": booking_account_id,
            "bank_account_id": bank_account_id,
            "attachment_ids": [file_uuid],
        }
        
        if receipt.merchant_name:
            payload["address"] = {"lastname_company": receipt.merchant_name, "type": "COMPANY"}
        
        resp = await self.client.post("/4.0/expenses", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def create_purchase_bill(self, receipt: Receipt, file_uuid: str,
                                    booking_account_id: int) -> Dict:
        """Create a full purchase bill with line items (bexio v4)."""
        supplier_id = await self.find_or_create_contact(receipt.merchant_name)
        
        line_items = []
        if receipt.vat_breakdown:
            for i, entry in enumerate(receipt.vat_breakdown):
                line_items.append({
                    "position": i,
                    "title": f"VAT {entry.rate}%",
                    "tax_id": await self.get_tax_id(entry.rate),
                    "amount": round(entry.base_amount + entry.vat_amount, 2),
                    "booking_account_id": booking_account_id
                })
        else:
            line_items.append({
                "position": 0,
                "title": receipt.merchant_name or "Receipt",
                "tax_id": await self.get_tax_id(receipt.vat_rate_pct),
                "amount": round(receipt.total_incl_vat, 2),
                "booking_account_id": booking_account_id
            })

        payload = {
            "supplier_id": supplier_id,
            "title": receipt.merchant_name or "Receipt",
            "contact_partner_id": supplier_id,
            "bill_date": receipt.date.isoformat(),
            "due_date": receipt.date.isoformat(),
            "amount_man": round(receipt.total_incl_vat, 2),
            "manual_amount": True,
            "currency_code": receipt.currency,
            "item_net": False, # Amounts in line items are gross
            "attachment_ids": [file_uuid],
            "address": {
                "lastname_company": receipt.merchant_name,
                "type": "COMPANY"
            },
            "line_items": line_items
        }
        
        resp = await self.client.post("/4.0/purchase/bills", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.client.aclose()
