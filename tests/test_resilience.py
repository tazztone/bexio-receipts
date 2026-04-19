import pytest
import httpx
from bexio_receipts.config import Settings
from bexio_receipts.bexio_client import BexioClient
from bexio_receipts.pipeline import process_receipt
from bexio_receipts.database import DuplicateDetector
import pytest_asyncio
import tempfile
from pathlib import Path

@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        yield DuplicateDetector(f.name)

@pytest.fixture
def mock_settings():
    return Settings(
        offline_mode=True,
        bexio_api_token="dummy",
        default_booking_account_id=0,
        default_bank_account_id=0,
        review_password="admin"
    )

@pytest.mark.asyncio
async def test_offline_mode_settings():
    # Settings should initialize without errors when offline_mode=True
    settings = Settings(
        offline_mode=True,
        bexio_api_token="dummy",
        default_booking_account_id=0,
        default_bank_account_id=0,
        review_password="admin"
    )
    assert settings.offline_mode is True

@pytest.mark.asyncio
async def test_cache_lookups_resilience(respx_mock):
    # Mock Bexio API to return 401
    respx_mock.get("https://api.bexio.com/3.0/users/me").mock(return_value=httpx.Response(401))
    respx_mock.get("https://api.bexio.com/3.0/taxes").mock(return_value=httpx.Response(401))
    respx_mock.get("https://api.bexio.com/2.0/accounts").mock(return_value=httpx.Response(401))

    async with BexioClient(token="dummy") as client:
        # This should NOT raise an exception
        await client.cache_lookups()
        
        # Caches should just be empty/none
        assert client._user_id is None
        assert not client._tax_cache
        assert not client._account_cache
