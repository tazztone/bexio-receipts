import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from bexio_receipts.gdrive_ingest import GoogleDriveIngestor
import structlog

@pytest.mark.asyncio
async def test_gdrive_credentials_permissions(test_settings, tmp_path):
    import stat
    import logging
    from structlog.testing import capture_logs

    creds_file = tmp_path / "creds.json"
    creds_file.touch()

    # Make it insecure (e.g. 644)
    creds_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    test_settings.gdrive_credentials_file = str(creds_file)
    bexio_mock = MagicMock()
    ingestor = GoogleDriveIngestor(test_settings, bexio_mock)

    with capture_logs() as cap_logs:
        try:
            await ingestor.connect()
        except Exception:
            pass

        assert any("insecure permissions" in log["event"] for log in cap_logs)

    # Make it secure (600)
    creds_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    with capture_logs() as cap_logs:
        try:
            await ingestor.connect()
        except Exception:
            pass

        assert not any("insecure permissions" in log["event"] for log in cap_logs)
