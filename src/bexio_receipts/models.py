"""
Pydantic data models for the bexio-receipts project.
Defines the structure of receipt data and internal state.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total: float


class RawVatRow(BaseModel):
    """Model only reads numbers off the receipt — no math required."""

    rate: float  # e.g. 8.1
    col_a: float  # first number in the VAT row
    col_b: float  # second number
    col_c: float | None  # third number (may be absent)


class RawReceipt(BaseModel):
    merchant_name: str | None = None
    transaction_date: str | None = None
    currency: str = "CHF"
    total_incl_vat: float | None = None  # the grand total — just read it
    vat_rows: list[RawVatRow] = []
    payment_method: str | None = None


class VatEntry(BaseModel):
    rate: float = Field(..., description="VAT rate in percent (e.g. 8.1, 2.6)")
    base_amount: float = Field(
        ..., description="Net amount the VAT is calculated on (exkl. MWST)"
    )
    vat_amount: float = Field(..., description="Actual VAT amount for this rate")
    total_incl_vat: float | None = Field(
        default=None,
        description="Amount including VAT (inkl. MWST) — optional, used for validation only",
    )

    @model_validator(mode="after")
    def check_vat_math(self) -> VatEntry:
        if self.total_incl_vat is not None:
            expected = round(self.base_amount + self.vat_amount, 2)
            if abs(expected - self.total_incl_vat) > 0.05:
                raise ValueError(
                    f"VAT math fails: {self.base_amount} + {self.vat_amount} "
                    f"= {expected} ≠ {self.total_incl_vat}"
                )
        return self


class Receipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    merchant_name: str | None = None
    transaction_date: date | None = Field(default=None, alias="date")
    currency: str = "CHF"
    subtotal_excl_vat: float | None = None
    vat_rate_pct: float | None = Field(
        default=None, description="Dominant Swiss VAT rate: 8.1, 2.6, 3.8, or 0.0"
    )
    vat_amount: float | None = None
    total_incl_vat: float | None = None
    vat_breakdown: list[VatEntry] = Field(
        default_factory=list,
        description="Breakdown of VAT per rate found on the receipt",
    )
    line_items: list[LineItem] | None = None
    payment_method: str | None = None  # card/cash/twint etc.
    invoice_number: str | None = None

    @model_validator(mode="after")
    def check_totals(self) -> Receipt:
        tol = 0.05
        if self.vat_breakdown:
            sum_vat = sum(e.vat_amount for e in self.vat_breakdown)
            sum_base = sum(e.base_amount for e in self.vat_breakdown)
            if self.vat_amount is not None and abs(sum_vat - self.vat_amount) > tol:
                raise ValueError(
                    f"vat_breakdown sum {sum_vat:.2f} ≠ vat_amount {self.vat_amount:.2f}"
                )
            if (
                self.subtotal_excl_vat is not None
                and abs(sum_base - self.subtotal_excl_vat) > tol
            ):
                raise ValueError(
                    f"vat_breakdown base sum {sum_base:.2f} ≠ subtotal_excl_vat {self.subtotal_excl_vat:.2f}"
                )

        if (
            self.subtotal_excl_vat is not None
            and self.vat_amount is not None
            and self.total_incl_vat is not None
        ):
            expected = round(self.subtotal_excl_vat + self.vat_amount, 2)
            if abs(expected - self.total_incl_vat) > tol:
                raise ValueError(
                    f"{self.subtotal_excl_vat} + {self.vat_amount} = {expected} ≠ {self.total_incl_vat}"
                )
        return self

    @field_validator("merchant_name", mode="after")
    @classmethod
    def normalize_merchant_name(cls, v: str | None) -> str | None:
        if v is None:
            return None

        # Collapse whitespace, preserve case
        return " ".join(v.split())
