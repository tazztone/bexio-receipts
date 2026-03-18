from bexio_receipts.models import Receipt
from datetime import date

r1 = Receipt(merchant_name="MIGROS", date=date.today(), total_incl_vat=10.0)
r2 = Receipt(merchant_name="Migros AG", date=date.today(), total_incl_vat=10.0)
r3 = Receipt(merchant_name="migros", date=date.today(), total_incl_vat=10.0)
r4 = Receipt(merchant_name="  My Shop GmbH  ", date=date.today(), total_incl_vat=10.0)

print(r1.merchant_name)
print(r2.merchant_name)
print(r3.merchant_name)
print(r4.merchant_name)
