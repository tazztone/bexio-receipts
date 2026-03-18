from pydantic import BaseModel, Field
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
    merchant_name: str | None = None
    date: date
    currency: str = "CHF"
    subtotal_excl_vat: float | None = None
    vat_rate_pct: float | None = Field(None, description="Dominant Swiss VAT rate: 8.1, 2.6, 3.8, or 0.0")
    vat_amount: float | None = None
    total_incl_vat: float
    vat_breakdown: list[VatEntry] = Field(default_factory=list, description="Breakdown of VAT per rate found on the receipt")
    line_items: list[LineItem] | None = None
    invoice_number: str | None = None
    payment_method: str | None = None  # card/cash/twint etc.
