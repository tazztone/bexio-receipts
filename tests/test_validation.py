from datetime import date, timedelta
from bexio_receipts.models import Receipt, LineItem
from bexio_receipts.validation import validate_receipt

def test_valid_receipt():
    receipt = Receipt(
        merchant_name="Coop",
        date=date.today(),
        currency="CHF",
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=0.81,
        total_incl_vat=10.81
    )
    errors = validate_receipt(receipt)
    assert len(errors) == 0

def test_rounding_tolerance():
    # 5 Rappen tolerance check
    receipt = Receipt(
        merchant_name="Migros",
        date=date.today(),
        currency="CHF",
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=0.85, # 0.81 + 0.04 (within 0.05)
        total_incl_vat=10.85
    )
    errors = validate_receipt(receipt)
    assert len(errors) == 0

def test_invalid_vat_rate():
    receipt = Receipt(
        merchant_name="Test",
        date=date.today(),
        vat_rate_pct=10.0, # Invalid for Switzerland
        total_incl_vat=11.0
    )
    errors = validate_receipt(receipt)
    assert any("Invalid Swiss VAT rate" in e for e in errors)

def test_future_date():
    receipt = Receipt(
        merchant_name="Future",
        date=date.today() + timedelta(days=1),
        total_incl_vat=10.0
    )
    errors = validate_receipt(receipt)
    assert any("Future date" in e for e in errors)

def test_line_items_mismatch():
    receipt = Receipt(
        merchant_name="Items",
        date=date.today(),
        subtotal_excl_vat=20.0,
        total_incl_vat=20.0,
        line_items=[
            LineItem(description="Item 1", unit_price=10.0, total=10.0),
            LineItem(description="Item 2", unit_price=11.0, total=11.0) # Sum = 21.0 != 20.0
        ]
    )
    errors = validate_receipt(receipt)
    assert any("Line items sum (21.0) ≠ subtotal (20.0)" in e for e in errors)
