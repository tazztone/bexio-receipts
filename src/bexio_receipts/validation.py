"""
Validation logic for Swiss VAT and business rules.
Ensures extracted receipt data complies with accounting requirements.
"""

from datetime import date, timedelta

from .config import Settings
from .models import Receipt

VALID_CH_VAT = {0.0, 2.5, 2.6, 3.8, 7.7, 8.1}


def _check_totals_integrity(r: Receipt, errors: list[str]) -> None:
    if (
        r.subtotal_excl_vat is not None
        and r.vat_amount is not None
        and r.total_incl_vat is not None
    ):
        expected = r.subtotal_excl_vat + r.vat_amount
        if abs(expected - r.total_incl_vat) > 0.05:
            errors.append(
                f"Total mismatch: {r.subtotal_excl_vat} + {r.vat_amount} ≠ {r.total_incl_vat}"
            )


def _check_vat_rate(r: Receipt, errors: list[str]) -> None:
    if r.vat_rate_pct is not None and r.vat_rate_pct not in VALID_CH_VAT:
        errors.append(f"Invalid Swiss VAT rate: {r.vat_rate_pct}%")


def _check_vat_back_calculation(r: Receipt, errors: list[str]) -> None:
    if (
        not r.vat_breakdown
        and r.vat_rate_pct is not None
        and r.subtotal_excl_vat is not None
        and r.vat_amount is not None
    ):
        expected_vat = round(r.subtotal_excl_vat * r.vat_rate_pct / 100, 2)
        if abs(expected_vat - r.vat_amount) > 0.05:
            errors.append(
                f"VAT amount doesn't match rate: {r.vat_rate_pct}% of {r.subtotal_excl_vat} ≠ {r.vat_amount}"
            )


def _check_date_sanity(
    r: Receipt, settings: Settings, errors: list[str], warnings: list[str]
) -> None:
    if r.transaction_date is None:
        errors.append("Missing date")
    else:
        if r.transaction_date > date.today():
            warnings.append(f"Future date: {r.transaction_date}")
        if r.transaction_date < date.today() - timedelta(
            days=settings.max_receipt_age_days
        ):
            warnings.append(
                f"Receipt older than {settings.max_receipt_age_days} days: {r.transaction_date}"
            )


def _check_amount_sanity(r: Receipt, errors: list[str]) -> None:
    if r.total_incl_vat is None:
        errors.append("Missing total amount")
    elif r.total_incl_vat <= 0:
        errors.append("Total must be positive")
    elif r.total_incl_vat > 10_000:
        errors.append(f"Unusually large amount: {r.total_incl_vat} CHF — manual review")


def _check_vat_breakdown(r: Receipt, errors: list[str]) -> None:
    if r.vat_breakdown:
        total_base = sum(v.base_amount for v in r.vat_breakdown)
        total_vat = sum(v.vat_amount for v in r.vat_breakdown)

        if (
            r.subtotal_excl_vat is not None
            and abs(total_base - r.subtotal_excl_vat) > 0.05
        ):
            errors.append(
                f"VAT breakdown base ({total_base}) ≠ subtotal ({r.subtotal_excl_vat})"
            )

        if r.vat_amount is not None and abs(total_vat - r.vat_amount) > 0.05:
            errors.append(
                f"VAT breakdown total ({total_vat}) ≠ extracted VAT amount ({r.vat_amount})"
            )

        if (
            r.total_incl_vat is not None
            and abs(total_base + total_vat - r.total_incl_vat) > 0.05
        ):
            errors.append(
                f"VAT breakdown sum ({total_base + total_vat}) ≠ total incl. VAT ({r.total_incl_vat})"
            )


def _check_currency(r: Receipt, errors: list[str]) -> None:
    if r.currency != "CHF":
        errors.append(
            f"Currency {r.currency} is not CHF. Check conversion rate before approving."
        )


def _check_line_items(r: Receipt, errors: list[str]) -> None:
    if r.line_items:
        items_total = sum(i.total for i in r.line_items)
        if (
            r.subtotal_excl_vat is not None
            and abs(items_total - r.subtotal_excl_vat) > 0.10
        ):
            errors.append(
                f"Line items sum ({items_total}) ≠ subtotal ({r.subtotal_excl_vat})"
            )
        elif (
            r.total_incl_vat is not None
            and r.subtotal_excl_vat is None
            and abs(items_total - r.total_incl_vat) > 0.10
        ):
            # If subtotal is missing, compare with total_incl_vat (approximate)
            errors.append(
                f"Line items sum ({items_total}) ≠ total incl. VAT ({r.total_incl_vat})"
            )


def validate_receipt(r: Receipt, settings: Settings) -> tuple[list[str], list[str]]:
    """
    Validate receipt data against Swiss business rules.
    Returns (errors, warnings). Only errors block booking.
    """
    errors = []
    warnings = []

    _check_totals_integrity(r, errors)
    _check_vat_rate(r, errors)
    _check_vat_back_calculation(r, errors)
    _check_date_sanity(r, settings, errors, warnings)
    _check_amount_sanity(r, errors)
    _check_vat_breakdown(r, errors)
    _check_currency(r, errors)
    _check_line_items(r, errors)

    return errors, warnings
