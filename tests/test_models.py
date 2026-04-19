from datetime import date

import pytest
from pydantic import ValidationError

from bexio_receipts.models import Receipt, VatEntry


def test_merchant_name_normalization():
    r1 = Receipt(
        merchant_name="MIGROS", transaction_date=date.today(), total_incl_vat=10.0
    )
    r2 = Receipt(
        merchant_name="Migros AG", transaction_date=date.today(), total_incl_vat=10.0
    )
    r3 = Receipt(
        merchant_name="migros", transaction_date=date.today(), total_incl_vat=10.0
    )
    r4 = Receipt(
        merchant_name="  My Shop GmbH  ",
        transaction_date=date.today(),
        total_incl_vat=10.0,
    )

    assert r1.merchant_name == "MIGROS"
    assert r2.merchant_name == "Migros AG"
    assert r3.merchant_name == "migros"
    assert r4.merchant_name == "My Shop GmbH"


def test_vat_entry_math_validation():
    # Valid math
    VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1, total_incl_vat=108.1)

    # Invalid math
    with pytest.raises(ValidationError):
        VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1, total_incl_vat=110.0)

    # Optional total_incl_vat (no validation)
    VatEntry(rate=8.1, base_amount=100.0, vat_amount=8.1)
