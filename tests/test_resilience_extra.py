import pytest
from unittest.mock import AsyncMock, patch
from bexio_receipts.cli import app
from bexio_receipts.config import Settings
from typer.testing import CliRunner
import json
import asyncio

runner = CliRunner()


@pytest.fixture
def mock_settings():
    return Settings(
        bexio_api_token="test_token",
        bexio_base_url="https://api.bexio.com/2.0",
        bexio_push_enabled=True,
        database_path="test.db",
        inbox_path="inbox",
        offline_mode=False,
        review_password="password",
        secret_key="secret",
    )


def _run_coroutine(coroutine):
    """Run a coroutine on a fresh event loop to prevent loop-reuse leaks."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def test_cli_cache_lookups_resilience_process(mock_settings, tmp_path):
    """Test that process command continues even if cache_lookups fails."""
    receipt_file = tmp_path / "receipt.jpg"
    receipt_file.write_text("dummy content")

    with (
        patch("bexio_receipts.cli.get_settings", return_value=mock_settings),
        patch("bexio_receipts.cli.BexioClient") as MockClient,
        patch(
            "bexio_receipts.cli.process_receipt", new_callable=AsyncMock
        ) as mock_process,
        patch(
            "bexio_receipts.cli.asyncio.run",
            side_effect=_run_coroutine,
        ),
    ):
        client_instance = MockClient.return_value.__aenter__.return_value
        client_instance.cache_lookups = AsyncMock(side_effect=Exception("Bexio Down"))

        mock_process.return_value = {"status": "success"}

        result = runner.invoke(app, ["process", str(receipt_file), "--push"])

        assert result.exit_code == 0
        assert "Warning: Failed to connect to Bexio" in result.output


def test_cli_cache_lookups_resilience_reprocess(mock_settings, tmp_path):
    """Test that reprocess command continues even if cache_lookups fails."""
    review_file = tmp_path / "review.json"
    orig_file = tmp_path / "receipt.jpg"
    orig_file.write_text("dummy")

    review_file.write_text(
        json.dumps({"id": "123", "original_file": str(orig_file), "merchant": "Test"})
    )

    with (
        patch("bexio_receipts.cli.get_settings", return_value=mock_settings),
        patch("bexio_receipts.cli.BexioClient") as MockClient,
        patch(
            "bexio_receipts.cli.process_receipt", new_callable=AsyncMock
        ) as mock_process,
        patch(
            "bexio_receipts.cli.asyncio.run",
            side_effect=_run_coroutine,
        ),
    ):
        client_instance = MockClient.return_value.__aenter__.return_value
        client_instance.cache_lookups = AsyncMock(side_effect=Exception("Bexio Down"))

        mock_process.return_value = {"status": "success"}

        result = runner.invoke(app, ["reprocess", str(review_file), "--push"])

        assert result.exit_code == 0
        assert "Warning: Failed to connect to Bexio" in result.output


def test_offline_mode_behavior():
    """Test that Settings works in offline mode without a token."""
    with patch.dict(
        "os.environ",
        {"OFFLINE_MODE": "true", "REVIEW_PASSWORD": "password", "SECRET_KEY": "secret"},
        clear=True,
    ):
        settings = Settings(_env_file=None)
        assert settings.offline_mode is True
        assert settings.bexio_api_token == "offline"


def test_watcher_email_resilience(mock_settings):
    """Test that email watcher command starts correctly."""
    with (
        patch("bexio_receipts.cli.get_settings", return_value=mock_settings),
        patch("bexio_receipts.cli.asyncio.run"),
    ):
        result = runner.invoke(app, ["watch", "email"])
        assert result.exit_code == 0


def test_watcher_telegram_resilience(mock_settings):
    """Test that telegram watcher command starts correctly."""
    with (
        patch("bexio_receipts.cli.get_settings", return_value=mock_settings),
        patch("bexio_receipts.cli.asyncio.run"),
    ):
        result = runner.invoke(app, ["watch", "telegram"])
        assert result.exit_code == 0
