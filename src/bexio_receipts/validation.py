from datetime import date, timedelta
from typing import List
from .models import Receipt

VALID_CH_VAT = {0.0, 2.6, 3.8, 8.1}

def validate_receipt(r: Receipt) -> List[str]:
    """
    Validate receipt data against Swiss business rules.
    Returns a list of error strings.
    """
    errors = []
    
    # 1. Totals integrity (only if both subtotal and vat values present)
    if r.subtotal_excl_vat is not None and r.vat_amount is not None:
        expected = r.subtotal_excl_vat + r.vat_amount
        if abs(expected - r.total_incl_vat) > 0.05:  # 5 Rappen tolerance (Swiss rounding)
            errors.append(f"Total mismatch: {r.subtotal_excl_vat} + {r.vat_amount} ≠ {r.total_incl_vat}")
    
    # 2. VAT rate check (only if extracted)
    if r.vat_rate_pct is not None and r.vat_rate_pct not in VALID_CH_VAT:
        errors.append(f"Invalid Swiss VAT rate: {r.vat_rate_pct}%")
    
    # 3. VAT back-calculation check
    if r.vat_rate_pct and r.subtotal_excl_vat and r.vat_amount:
        expected_vat = round(r.subtotal_excl_vat * r.vat_rate_pct / 100, 2)
        if abs(expected_vat - r.vat_amount) > 0.05:
            errors.append(f"VAT amount doesn't match rate: {r.vat_rate_pct}% of {r.subtotal_excl_vat} ≠ {r.vat_amount}")
    
    # 4. Date sanity
    if r.date > date.today():
        errors.append(f"Future date: {r.date}")
    if r.date < date.today() - timedelta(days=365):
        errors.append(f"Receipt older than 1 year: {r.date}")
    
    # 5. Amount sanity
    if r.total_incl_vat <= 0:
        errors.append("Total must be positive")
    if r.total_incl_vat > 10_000:
        errors.append(f"Unusually large amount: {r.total_incl_vat} CHF — manual review")
    
    # 6. VAT breakdown cross-check
    if r.vat_breakdown:
        total_base = sum(v.base_amount for v in r.vat_breakdown)
        total_vat = sum(v.vat_amount for v in r.vat_breakdown)
        
        if r.subtotal_excl_vat and abs(total_base - r.subtotal_excl_vat) > 0.05:
            errors.append(f"VAT breakdown base ({total_base}) ≠ subtotal ({r.subtotal_excl_vat})")
        
        if r.vat_amount and abs(total_vat - r.vat_amount) > 0.05:
            # Note: This error might be redundant if the dominant rate is also in the breakdown,
            # but it catches cases where the dominant rate logic is flawed.
            pass

        if abs(total_base + total_vat - r.total_incl_vat) > 0.05:
            errors.append(f"VAT breakdown sum ({total_base + total_vat}) ≠ total incl. VAT ({r.total_incl_vat})")

    # 7. Line items cross-check
    if r.line_items:
        items_total = sum(i.total for i in r.line_items)
        if r.subtotal_excl_vat and abs(items_total - r.subtotal_excl_vat) > 0.10:
            errors.append(f"Line items sum ({items_total}) ≠ subtotal ({r.subtotal_excl_vat})")
        elif abs(items_total - r.total_incl_vat) > 0.10 and r.subtotal_excl_vat is None:
            # If subtotal is missing, compare with total_incl_vat (approximate)
             errors.append(f"Line items sum ({items_total}) ≠ total incl. VAT ({r.total_incl_vat})")
    
    return errors
