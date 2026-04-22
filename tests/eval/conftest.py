import json
import os
import pathlib

import pytest

# Bootstrap env vars before Settings import (mirrors tests/conftest.py)
os.environ.setdefault("BEXIO_API_TOKEN", "dummy")
os.environ.setdefault("REVIEW_PASSWORD", "dummy")
os.environ.setdefault("SECRET_KEY", "dummy")
os.environ.setdefault("DEFAULT_BOOKING_ACCOUNT_ID", "1")
os.environ.setdefault("DEFAULT_BANK_ACCOUNT_ID", "2")

from bexio_receipts.config import Settings

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_golden() -> list[tuple[pathlib.Path, dict]]:
    """Return [(img_path, metadata), ...] for every vision fixture.

    Returns empty list if fixture dir missing or empty — prevents
    import-time crashes during pytest collection.
    """
    if not FIXTURE_DIR.exists():
        return []

    results = []
    for json_file in sorted(FIXTURE_DIR.glob("*.json")):
        try:
            meta = json.loads(json_file.read_text())
        except json.JSONDecodeError:
            continue

        if meta.get("source") != "vision":
            continue

        # Try .jpg then .png
        img_path = FIXTURE_DIR / f"{json_file.stem}.jpg"
        if not img_path.exists():
            img_path = FIXTURE_DIR / f"{json_file.stem}.png"
        if not img_path.exists():
            continue  # skip silently — CI may not have all images

        results.append((img_path, meta))
    return results


@pytest.fixture(scope="session")
def eval_settings():
    """Real settings for live vLLM. Server must already be running."""
    return Settings(
        processor_mode="vision",
        vision_manage_server=False,
    )
