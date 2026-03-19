from __future__ import annotations
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import date
import re


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
    model_config = ConfigDict(populate_by_name=True)

    merchant_name: str | None = None
    transaction_date: date | None = Field(None, alias="date")
    currency: str = "CHF"
    subtotal_excl_vat: float | None = None
    vat_rate_pct: float | None = Field(
        None, description="Dominant Swiss VAT rate: 8.1, 2.6, 3.8, or 0.0"
    )
    vat_amount: float | None = None
    total_incl_vat: float | None = None
    vat_breakdown: list[VatEntry] = Field(
        default_factory=list,
        description="Breakdown of VAT per rate found on the receipt",
    )
    line_items: list[LineItem] | None = None
    invoice_number: str | None = None
    payment_method: str | None = None  # card/cash/twint etc.

    @field_validator("merchant_name", mode="after")
    @classmethod
    def normalize_merchant_name(cls, v: str | None) -> str | None:
        if v is None:
            return None

        # Strip and Title Case
        v = v.strip().title()

        # Remove common suffixes (case-insensitive because it's already title cased)
        suffixes = r"\s+(Ag|Gmbh|Ltd\.?|Inc\.?)$"
        v = re.sub(suffixes, "", v, flags=re.IGNORECASE)

        return v.strip()
