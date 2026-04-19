import pytest

from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.models import Receipt


@pytest.mark.asyncio
async def test_bexio_client_read_only_by_default():
    """Verify that BexioClient defaults to read-only and prevents writes."""
    client = BexioClient(token="fake-token")

    with pytest.raises(RuntimeError, match="Bexio write operations are disabled"):
        await client.upload_file("fake.jpg", "fake.jpg", "image/jpeg")

    receipt = Receipt(merchant_name="Test", total_incl_vat=10.0)

    with pytest.raises(RuntimeError, match="Bexio write operations are disabled"):
        await client.create_expense(receipt, "uuid", 1, 1)

    with pytest.raises(RuntimeError, match="Bexio write operations are disabled"):
        await client.create_purchase_bill(receipt, "uuid", 1)


@pytest.mark.asyncio
async def test_bexio_client_contact_creation_guarded():
    """Verify that contact creation is also guarded."""
    client = BexioClient(token="fake-token", push_enabled=False)

    with pytest.raises(RuntimeError, match="Bexio write operations are disabled"):
        await client.find_or_create_contact("New Merchant")
