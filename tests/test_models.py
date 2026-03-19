from bexio_receipts.models import Receipt
from datetime import date


def test_merchant_name_normalization():
    r1 = Receipt(merchant_name="MIGROS", date=date.today(), total_incl_vat=10.0)
    r2 = Receipt(merchant_name="Migros AG", date=date.today(), total_incl_vat=10.0)
    r3 = Receipt(merchant_name="migros", date=date.today(), total_incl_vat=10.0)
    r4 = Receipt(
        merchant_name="  My Shop GmbH  ", date=date.today(), total_incl_vat=10.0
    )

    assert r1.merchant_name == "Migros"
    assert r2.merchant_name == "Migros Ag"
    assert r3.merchant_name == "Migros"
    assert r4.merchant_name == "My Shop Gmbh"
