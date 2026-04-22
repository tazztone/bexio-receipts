"""
Pydantic data models for the bexio-receipts project.
Defines the structure of receipt data and internal state.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountAssignment(BaseModel):
    vat_rate: float  # 2.6 or 8.1
    account_id: str  # "4200"
    account_name: str  # "Einkauf Handelsware"
    confidence: Literal["high", "medium", "low"]
    reasoning: str  # one sentence — for review queue visibility


class AccountAssignments(BaseModel):
    """Wrapper for list[AccountAssignment] as pydantic-ai doesn't support bare lists for some models."""

    assignments: list[AccountAssignment]


class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total: float


class RawVatRow(BaseModel):
    """Model only reads numbers off the receipt — no math required."""

    rate: float  # e.g. 8.1
    # Legacy columns (Step 2 positional data)
    col_a: float | None = None
    col_b: float | None = None
    col_c: float | None = None
    # Semantic columns (Vision / High-fidelity LLM)
    net_amount: float | None = None
    vat_amount: float | None = None
    total_amount: float | None = None


class RawVatRows(BaseModel):
    """Wrapper for list[RawVatRow] for consistent LLM responses."""

    rows: list[RawVatRow]


class RawReceipt(BaseModel):
    merchant_name: str | None = None
    transaction_date: str | None = None
    currency: str = "CHF"
    total_incl_vat: float | None = None
    vat_rows: list[RawVatRow] = []
    account_assignments: list[AccountAssignment] = []
    payment_method: str | None = None


class IntermediateReceipt(BaseModel):
    """Output of Step 1: Preliminary extraction including raw VAT text."""

    merchant_name: str = Field(..., min_length=1)
    transaction_date: str
    currency: str = "CHF"
    total_incl_vat: float
    vat_table_raw: str = Field(
        ...,
        description="Copy the raw VAT table (HTML or plain text) verbatim.",
    )
    payment_method: str | None = None

    @field_validator("total_incl_vat")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("total_incl_vat must be positive")
        return v


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
    account_assignments: list[AccountAssignment] = Field(
        default_factory=list, description="Suggested booking accounts per VAT rate"
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


class VisionExtraction(BaseModel):
    """Schema for Qwen3.6 vision-language extraction."""

    merchant_name: str | None = Field(None, description="Name of the vendor/store")
    transaction_date: str | None = Field(None, description="ISO date YYYY-MM-DD")
    currency: str = Field("CHF", description="3-letter currency code")
    subtotal_excl_vat: float | None = Field(None, description="Total net amount")
    vat_rate_pct: float | None = Field(None, description="Primary VAT rate (%)")
    vat_amount: float | None = Field(None, description="Primary VAT amount")
    total_incl_vat: float | None = Field(None, description="Grand total amount")
    vat_rows: list[RawVatRow] = Field(
        default_factory=list, description="List of all VAT lines"
    )
    account_assignments: list[AccountAssignment] = Field(
        default_factory=list, description="Suggested booking accounts per VAT rate"
    )
