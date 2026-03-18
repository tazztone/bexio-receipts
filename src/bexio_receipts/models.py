from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total: float

class VatEntry(BaseModel):
    rate: float = Field(..., description="VAT rate in percent (e.g. 8.1, 2.6)")
    base_amount: float = Field(..., description="Net amount the VAT is calculated on")
    vat_amount: float = Field(..., description="Actual VAT amount for this rate")

class Receipt(BaseModel):
    merchant_name: str
    date: date
    currency: str = "CHF"
    subtotal_excl_vat: Optional[float] = None
    vat_rate_pct: Optional[float] = Field(None, description="Dominant Swiss VAT rate: 8.1, 2.6, 3.8, or 0.0")
    vat_amount: Optional[float] = None
    total_incl_vat: float
    vat_breakdown: List[VatEntry] = Field(default_factory=list, description="Breakdown of VAT per rate found on the receipt")
    line_items: Optional[List[LineItem]] = None
    invoice_number: Optional[str] = None
    payment_method: Optional[str] = None  # card/cash/twint etc.
