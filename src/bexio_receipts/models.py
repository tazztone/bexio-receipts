from pydantic import BaseModel, Field
from typing import Optional, List
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
    line_items: Optional[List[LineItem]] = None
    invoice_number: Optional[str] = None
    payment_method: Optional[str] = None  # card/cash/twint etc.
