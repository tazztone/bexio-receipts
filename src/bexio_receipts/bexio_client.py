import httpx
import structlog
from datetime import date
from .models import Receipt
from typing import Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = structlog.get_logger(__name__)

CONTACT_TYPE_COMPANY = 1
CONTACT_TYPE_PERSON = 2

def is_retryable_exception(exception: BaseException) -> bool:
    """Retries on 429 and 5xx errors from httpx."""
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code == 429 or 500 <= exception.response.status_code < 600
    return False

BEXIO_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(is_retryable_exception),
    reraise=True
)

class BexioClient:
    def __init__(self, token: str, base_url: str = "https://api.bexio.com", default_vat_rate: float = 8.1):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0,
        )
        self.default_vat_rate = default_vat_rate
        self._tax_cache: dict[float, int] = {}
        self._account_cache: dict[str, int] = {}
        self._user_id: int | None = None
        self._owner_id: int | None = None
    
    @BEXIO_RETRY
    async def get_profile(self) -> dict:
        """Fetch current user profile to get user_id and owner_id."""
        resp = await self.client.get("/3.0/profile/me")
        resp.raise_for_status()
        profile = resp.json()
        self._user_id = profile.get("id")

        # Try to get the actual tenant owner ID from company profile
        try:
            comp_resp = await self.client.get("/2.0/company_profile")
            comp_resp.raise_for_status()
            self._owner_id = comp_resp.json().get("owner_id", 1)
        except Exception as e:
            logger.warning("Failed to fetch company profile owner_id, defaulting to 1", error=str(e))
            self._owner_id = 1

        return profile

    @BEXIO_RETRY
    async def fetch_taxes(self):
        """Fetch and cache tax rates."""
        resp = await self.client.get("/3.0/taxes")
        resp.raise_for_status()
        taxes = resp.json()
        for t in taxes:
            if t.get("value") is not None:
                self._tax_cache[float(t["value"])] = t["id"]

    @BEXIO_RETRY
    async def fetch_accounts(self):
        """Fetch and cache accounts."""
        resp = await self.client.get("/2.0/accounts")
        resp.raise_for_status()
        accounts = resp.json()
        for a in accounts:
            if "account_no" in a:
                self._account_cache[str(a["account_no"])] = a["id"]

    async def cache_lookups(self):
        """Fetch and cache tenant-specific IDs at startup."""
        # User profile
        if not self._user_id:
            await self.get_profile()

        # Tax rates
        await self.fetch_taxes()
        
        # Accounts
        await self.fetch_accounts()
    
    async def get_tax_id(self, rate: float | None) -> int:
        """Return bexio tax ID for a given rate, fallback to standard default."""
        if rate is None:
            return self._tax_cache.get(self.default_vat_rate, 1) # Fallback to standard
        return self._tax_cache.get(float(rate), self._tax_cache.get(self.default_vat_rate, 1))

    @BEXIO_RETRY
    async def upload_file(self, file_path: str, filename: str, mime_type: str) -> str:
        """Upload file, returns UUID string."""
        with open(file_path, "rb") as f:
            resp = await self.client.post(
                "/3.0/files",
                files={"file": (filename, f, mime_type)},
            )
            resp.raise_for_status()
            return resp.json()["id"]  # UUID string

    @BEXIO_RETRY
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
            "contact_type_id": CONTACT_TYPE_COMPANY,
            "name_1": name,
            "user_id": self._user_id or 1,
            "owner_id": self._owner_id or 1,
        }
        resp = await self.client.post("/2.0/contact", json=create_payload)
        resp.raise_for_status()
        return resp.json()["id"]

    @BEXIO_RETRY
    async def create_expense(self, receipt: Receipt, file_uuid: str, 
                              booking_account_id: int, bank_account_id: int) -> dict:
        """Create a simple expense (bexio v4)."""
        if receipt.vat_breakdown and len(receipt.vat_breakdown) > 1:
            logger.warning(
                "Multiple VAT rates detected, but bexio Expenses only support one tax_id. "
                "Using dominant rate.",
                breakdown=receipt.vat_breakdown
            )

        if receipt.total_incl_vat is None:
            raise ValueError("Total amount is required to create a bexio record")

        payload: dict[str, Any] = {
            "title": receipt.merchant_name,
            "paid_on": (receipt.transaction_date or date.today()).isoformat(),
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

    @BEXIO_RETRY
    async def create_purchase_bill(self, receipt: Receipt, file_uuid: str,
                                    booking_account_id: int) -> dict:
        """Create a full purchase bill with line items (bexio v4)."""
        if receipt.total_incl_vat is None:
            raise ValueError("Total amount is required to create a bexio record")
            
        if not receipt.merchant_name:
            raise ValueError("Merchant name is required to create a purchase bill")
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
            "bill_date": (receipt.transaction_date or date.today()).isoformat(),
            "due_date": (receipt.transaction_date or date.today()).isoformat(),
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
