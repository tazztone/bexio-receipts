import os

# Set required environment variables before importing any app modules
# to prevent Pydantic ValidationError on startup during testing.
os.environ["BEXIO_API_TOKEN"] = "dummy_token_for_tests"
os.environ["REVIEW_PASSWORD"] = (
    "$2b$04$W4vNXIM.I1MUZ1X1ooeHbeBbptF.QpqaRIlgz1s3yzAuw1o16flLK"
)
os.environ["SECRET_KEY"] = "dummy_secret_key_for_tests"
os.environ["DEFAULT_BOOKING_ACCOUNT_ID"] = "1"
os.environ["DEFAULT_BANK_ACCOUNT_ID"] = "2"
# Prevent local .env from enabling skip-auth and masking 401 tests
os.environ["REVIEW_SKIP_AUTH"] = "false"

from unittest.mock import AsyncMock, patch

import pytest

from bexio_receipts.config import Settings
from bexio_receipts.database import DuplicateDetector


@pytest.fixture
def test_settings():
    return Settings(
        bexio_api_token="test_token",
        review_password="$2b$04$W4vNXIM.I1MUZ1X1ooeHbeBbptF.QpqaRIlgz1s3yzAuw1o16flLK",
        secret_key="test_secret_key",
        default_booking_account_id=1,
        default_bank_account_id=2,
        glm_ocr_api_host="localhost",
        glm_ocr_api_port=8080,
        glm_ocr_manage_server=False,
        vision_manage_server=False,
        llm_provider="ollama",
        llm_model="qwen3.5",
        bexio_push_enabled=True,
    )


@pytest.fixture(autouse=True)
def mock_vllm_lifecycle():
    """Globally prevent starting real vLLM servers during tests."""
    with (
        patch("bexio_receipts.vllm_server.start_vllm_server", new_callable=AsyncMock),
        patch("bexio_receipts.vllm_server.stop_vllm_server"),
        patch(
            "bexio_receipts.document_processor.start_vllm_server",
            new_callable=AsyncMock,
        ),
        patch("bexio_receipts.ocr.start_vllm_server", new_callable=AsyncMock),
        patch("bexio_receipts.ocr.stop_vllm_server"),
    ):
        yield


@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    return DuplicateDetector(str(db_path))
