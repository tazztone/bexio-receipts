"""
Validation logic for Swiss VAT and business rules.
Ensures extracted receipt data complies with accounting requirements.
"""

from datetime import date, timedelta

from .config import Settings
from .models import Receipt

VALID_CH_VAT = {0.0, 2.6, 3.8, 8.1}


def validate_receipt(r: Receipt, settings: Settings) -> list[str]:
    """
    Validate receipt data against Swiss business rules.
    Returns a list of error strings.
    """
    errors = []

    # 1. Totals integrity (only if both subtotal and vat values present)
    if (
        r.subtotal_excl_vat is not None
        and r.vat_amount is not None
        and r.total_incl_vat is not None
    ):
        expected = r.subtotal_excl_vat + r.vat_amount
        if (
            abs(expected - r.total_incl_vat) > 0.05
        ):  # 5 Rappen tolerance (Swiss rounding)
            errors.append(
                f"Total mismatch: {r.subtotal_excl_vat} + {r.vat_amount} ≠ {r.total_incl_vat}"
            )

    # 2. VAT rate check (only if extracted)
    if r.vat_rate_pct is not None and r.vat_rate_pct not in VALID_CH_VAT:
        errors.append(f"Invalid Swiss VAT rate: {r.vat_rate_pct}%")

    # 3. VAT back-calculation check (only for single-rate receipts)
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

    # 4. Date sanity
    if r.transaction_date is None:
        errors.append("Missing date")
    else:
        if r.transaction_date > date.today():
            errors.append(f"[WARNING] Future date: {r.transaction_date}")
        if r.transaction_date < date.today() - timedelta(
            days=settings.max_receipt_age_days
        ):
            errors.append(
                f"Receipt older than {settings.max_receipt_age_days} days: {r.transaction_date}"
            )

    # 5. Amount sanity
    if r.total_incl_vat is None:
        errors.append("Missing total amount")
    elif r.total_incl_vat <= 0:
        errors.append("Total must be positive")
    elif r.total_incl_vat > 10_000:
        errors.append(f"Unusually large amount: {r.total_incl_vat} CHF — manual review")

    # 6. VAT breakdown cross-check
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

    # 7. Currency check
    if r.currency != "CHF":
        errors.append(
            f"Currency {r.currency} is not CHF. Check conversion rate before approving."
        )

    # 8. Line items cross-check
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

    return errors
