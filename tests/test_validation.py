from datetime import date, timedelta

from bexio_receipts.models import LineItem, Receipt, VatEntry
from bexio_receipts.validation import validate_receipt


def test_valid_receipt(test_settings):
    receipt = Receipt(
        merchant_name="Coop",
        transaction_date=date.today(),
        currency="CHF",
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=0.81,
        total_incl_vat=10.81,
    )
    errors = validate_receipt(receipt, test_settings)
    assert not errors


def test_rounding_tolerance(test_settings):
    # 5 Rappen tolerance check
    receipt = Receipt(
        merchant_name="Migros",
        transaction_date=date.today(),
        currency="CHF",
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=0.85,  # 0.81 + 0.04 (within 0.05)
        total_incl_vat=10.85,
    )
    errors = validate_receipt(receipt, test_settings)
    assert not errors


def test_invalid_vat_rate(test_settings):
    receipt = Receipt(
        merchant_name="Test",
        transaction_date=date.today(),
        vat_rate_pct=10.0,  # Invalid for Switzerland
        total_incl_vat=11.0,
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Invalid Swiss VAT rate" in e for e in errors)


def test_future_date(test_settings):
    receipt = Receipt(
        merchant_name="Future",
        transaction_date=date.today() + timedelta(days=1),
        total_incl_vat=10.0,
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Future date" in e for e in errors)


def test_old_date(test_settings):
    receipt = Receipt(
        merchant_name="Old",
        transaction_date=date.today() - timedelta(days=366),
        total_incl_vat=10.0,
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Receipt older than 365 days" in e for e in errors)


def test_line_items_mismatch(test_settings):
    receipt = Receipt(
        merchant_name="Items",
        transaction_date=date.today(),
        subtotal_excl_vat=20.0,
        total_incl_vat=20.0,
        line_items=[
            LineItem(description="Item 1", unit_price=10.0, total=10.0),
            LineItem(
                description="Item 2", unit_price=11.0, total=11.0
            ),  # Sum = 21.0 != 20.0
        ],
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Line items sum" in e for e in errors)


def test_missing_date(test_settings):
    # Receipt model actually requires `date` to be passed and not be None by pydantic
    # We can test validation logic by bypassing the model validation via construct
    receipt = Receipt.model_construct(
        merchant_name="No Date", transaction_date=None, total_incl_vat=10.0
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Missing date" in e for e in errors)


def test_zero_vat_total(test_settings):
    receipt = Receipt(
        merchant_name="Zero Total", transaction_date=date.today(), total_incl_vat=0.0
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Total must be positive" in e for e in errors)

    receipt2 = Receipt(
        merchant_name="Negative Total",
        transaction_date=date.today(),
        total_incl_vat=-5.0,
    )
    errors2 = validate_receipt(receipt2, test_settings)
    assert any("Total must be positive" in e for e in errors2)


def test_large_amount(test_settings):
    receipt = Receipt(
        merchant_name="Big Spender",
        transaction_date=date.today(),
        total_incl_vat=15000.0,
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Unusually large amount" in e for e in errors)


def test_missing_merchant(test_settings):
    # Depending on requirements missing merchant might just be an empty name and not an explicit error
    # Our validation logic doesn't explicitly throw an error for missing merchant currently but
    # it's good to ensure it doesn't crash
    receipt = Receipt(
        merchant_name=None, transaction_date=date.today(), total_incl_vat=10.0
    )
    errors = validate_receipt(receipt, test_settings)
    assert len(errors) == 0


def test_vat_back_calculation_mismatch(test_settings):
    receipt = Receipt.model_construct(
        merchant_name="VAT Calc",
        transaction_date=date.today(),
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=2.0,  # 8.1% of 10 is 0.81, so 2.0 is wrong
        total_incl_vat=12.0,
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("VAT amount doesn't match rate" in e for e in errors)


def test_vat_breakdown_cross_check(test_settings):
    receipt = Receipt.model_construct(
        merchant_name="Breakdown Check",
        transaction_date=date.today(),
        subtotal_excl_vat=10.0,
        vat_rate_pct=8.1,
        vat_amount=0.81,
        total_incl_vat=10.81,
        vat_breakdown=[
            VatEntry(
                rate=8.1, base_amount=15.0, vat_amount=1.21
            )  # Base is 15.0 != subtotal 10.0
        ],
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("VAT breakdown base (15.0) ≠ subtotal (10.0)" in e for e in errors)
    assert any(
        "VAT breakdown total (1.21) ≠ extracted VAT amount (0.81)" in e for e in errors
    )
    assert any(
        "VAT breakdown sum (16.21) ≠ total incl. VAT (10.81)" in e for e in errors
    )


def test_line_items_mismatch_no_subtotal(test_settings):
    receipt = Receipt(
        merchant_name="Items No Sub",
        transaction_date=date.today(),
        total_incl_vat=20.0,
        line_items=[
            LineItem(description="Item 1", unit_price=10.0, total=10.0),
            LineItem(
                description="Item 2", unit_price=11.0, total=11.0
            ),  # Sum = 21.0 != total 20.0
        ],
    )
    errors = validate_receipt(receipt, test_settings)
    assert any("Line items sum (21.0) ≠ total incl. VAT (20.0)" in e for e in errors)
