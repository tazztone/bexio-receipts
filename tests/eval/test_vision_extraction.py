"""
Vision eval suite — runs against live vLLM.
Requires: vLLM serving vision model on VISION_API_HOST:VISION_API_PORT.

Run:  pytest tests/eval/ -v -m eval
"""

import pytest

from bexio_receipts.document_processor import VisionProcessor

from .conftest import load_golden

pytestmark = pytest.mark.eval

_GOLDEN = load_golden()
_IDS = [m["receipt_id"] for _, m in _GOLDEN]


def _skip_if_empty():
    if not _GOLDEN:
        pytest.skip("No eval fixtures found (missing images?)")


@pytest.mark.parametrize("img_path,expected", _GOLDEN, ids=_IDS)
@pytest.mark.asyncio
async def test_required_fields_present(img_path, expected, eval_settings):
    _skip_if_empty()
    result = await VisionProcessor().process(str(img_path), eval_settings)
    assert result.confidence == 1.0, (
        f"[{expected['receipt_id']}] Missing required field.\n"
        f"raw VLM output:\n{result.raw_text[:500]}"
    )


@pytest.mark.parametrize("img_path,expected", _GOLDEN, ids=_IDS)
@pytest.mark.asyncio
async def test_totals(img_path, expected, eval_settings):
    _skip_if_empty()
    result = await VisionProcessor().process(str(img_path), eval_settings)

    assert result.total_incl_vat == pytest.approx(expected["total_incl_vat"], abs=0.05)

    if "subtotal_excl_vat" in expected:
        assert result.subtotal_excl_vat == pytest.approx(
            expected["subtotal_excl_vat"], abs=0.05
        )

    if "vat_amount" in expected:
        assert result.vat_amount == pytest.approx(expected["vat_amount"], abs=0.05)


@pytest.mark.parametrize("img_path,expected", _GOLDEN, ids=_IDS)
@pytest.mark.asyncio
async def test_vat_rows(img_path, expected, eval_settings):
    _skip_if_empty()
    result = await VisionProcessor().process(str(img_path), eval_settings)

    actual_rows = sorted(result.vat_rows, key=lambda r: r.rate)
    exp_rows = sorted(expected["vat_rows"], key=lambda r: r["rate"])

    assert len(actual_rows) == len(exp_rows), (
        f"VAT row count: got {len(actual_rows)}, expected {len(exp_rows)}\n"
        f"actual rates: {[r.rate for r in actual_rows]}"
    )

    for a, e in zip(actual_rows, exp_rows, strict=True):
        assert a.rate == e["rate"], f"rate mismatch: {a.rate} vs {e['rate']}"
        # Vision extraction uses semantic fields net_amount/vat_amount
        assert a.net_amount == pytest.approx(e["net_amount"], abs=0.05)
        assert a.vat_amount == pytest.approx(e["vat_amount"], abs=0.05)


@pytest.mark.parametrize("img_path,expected", _GOLDEN, ids=_IDS)
@pytest.mark.asyncio
async def test_account_assignments(img_path, expected, eval_settings):
    _skip_if_empty()
    result = await VisionProcessor().process(str(img_path), eval_settings)

    actual = {a.vat_rate: a.account_id for a in result.account_assignments}
    for exp in expected["account_assignments"]:
        rate = exp["vat_rate"]
        got = actual.get(rate)
        reasoning = next(
            (a.reasoning for a in result.account_assignments if a.vat_rate == rate),
            "n/a",
        )
        assert got == exp["account_id"], (
            f"account @ {rate}%: got {got!r}, expected {exp['account_id']!r}\n"
            f"LLM reasoning: {reasoning}"
        )


@pytest.mark.parametrize("img_path,expected", _GOLDEN, ids=_IDS)
@pytest.mark.asyncio
async def test_payment_method(img_path, expected, eval_settings):
    _skip_if_empty()
    result = await VisionProcessor().process(str(img_path), eval_settings)
    assert result.payment_method == expected["payment_method"]
