import json
from pathlib import Path

import httpx
import pytest

from bexio_receipts.config import Settings
from bexio_receipts.extraction import extract_receipt
from bexio_receipts.ocr import async_run_ocr


@pytest.mark.local_e2e
@pytest.mark.asyncio
async def test_prodega_ground_truth_e2e():
    """
    End-to-end integration test using the real Prodega receipt image.
    Requires live LLM and OCR services.
    """
    # Load settings from environment/.env
    settings = Settings()

    # Paths to fixtures
    fixtures_dir = Path(__file__).parent / "fixtures"
    image_path = fixtures_dir / "20260419_095459.jpg"
    truth_path = fixtures_dir / "prodega_ground_truth.json"

    if not image_path.exists():
        pytest.skip(f"Test image not found at {image_path}")

    if not truth_path.exists():
        pytest.skip(f"Ground truth JSON not found at {truth_path}")

    with open(truth_path) as f:
        ground_truth = json.load(f)

    # Use a longer timeout for E2E
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=5.0, pool=2.0)
    ) as client:
        # 1. OCR Stage
        print(f"\n[E2E] Running OCR on {image_path.name}...")
        raw_text, _, _ = await async_run_ocr(str(image_path), settings, client=client)
        assert len(raw_text) > 100, "OCR returned suspiciously short text"

        # 2. Extraction Stage
        print(
            f"[E2E] Extracting data using {settings.llm_model} ({settings.llm_provider})..."
        )
        receipt, trace = await extract_receipt(raw_text, settings, client=client)

    # 3. Assertions with detailed output on failure
    try:
        # Flexible merchant name check
        assert receipt.merchant_name, "Merchant name is missing"
        assert ground_truth["merchant_name"].upper() in receipt.merchant_name.upper(), (
            f"Merchant name mismatch: {receipt.merchant_name} vs {ground_truth['merchant_name']}"
        )

        assert str(receipt.transaction_date) == ground_truth["transaction_date"], (
            f"Date mismatch: {receipt.transaction_date} vs {ground_truth['transaction_date']}"
        )

        assert receipt.currency == ground_truth["currency"], (
            f"Currency mismatch: {receipt.currency} vs {ground_truth['currency']}"
        )

        assert receipt.total_incl_vat == pytest.approx(
            ground_truth["total_incl_vat"], abs=0.01
        ), (
            f"Total mismatch: {receipt.total_incl_vat} vs {ground_truth['total_incl_vat']}"
        )

        assert receipt.subtotal_excl_vat == pytest.approx(
            ground_truth["subtotal_excl_vat"], abs=0.01
        ), (
            f"Subtotal mismatch: {receipt.subtotal_excl_vat} vs {ground_truth['subtotal_excl_vat']}"
        )

        assert receipt.vat_amount == pytest.approx(
            ground_truth["vat_amount"], abs=0.01
        ), f"Total VAT mismatch: {receipt.vat_amount} vs {ground_truth['vat_amount']}"

        # VAT Breakdown checks
        assert len(receipt.vat_breakdown) == len(ground_truth["vat_breakdown"]), (
            f"VAT breakdown length mismatch: {len(receipt.vat_breakdown)} vs {len(ground_truth['vat_breakdown'])}"
        )

        for expected in ground_truth["vat_breakdown"]:
            # Find matching rate (allow small float diff in rate identification)
            match = next(
                (
                    v
                    for v in receipt.vat_breakdown
                    if abs(v.rate - expected["rate"]) < 0.1
                ),
                None,
            )
            assert match is not None, (
                f"VAT rate {expected['rate']}% missing from breakdown. Found rates: {[v.rate for v in receipt.vat_breakdown]}"
            )

            assert match.vat_amount == pytest.approx(
                expected["vat_amount"], abs=0.01
            ), (
                f"VAT amount mismatch for {expected['rate']}%: {match.vat_amount} vs {expected['vat_amount']}"
            )

            assert match.base_amount == pytest.approx(
                expected["base_amount"], abs=0.01
            ), (
                f"Base amount mismatch for {expected['rate']}%: {match.base_amount} vs {expected['base_amount']}"
            )

        print("\n[E2E] SUCCESS: Extraction matches ground truth perfectly!")

    except Exception as e:
        print(f"\n[E2E] FAILURE: {e}")

        # Handle custom ExtractionError which carries the full trace
        from bexio_receipts.extraction import ExtractionError

        if isinstance(e, ExtractionError) and e.trace:
            print("-" * 40)
            print("EXTRACTION TRACE (from Error):")
            print(e.trace.model_dump_json(indent=2))

        if "trace" in locals() and trace:
            print("-" * 40)
            print("EXTRACTION TRACE (from local):")
            print(trace.model_dump_json(indent=2))

        if "receipt" in locals() and receipt:
            print("-" * 40)
            print("EXTRACTED RECEIPT OBJECT:")
            print(receipt.model_dump_json(indent=2))

        # Failure-path assertion: verify trace was saved in review JSON if generated
        review_file = Path("review_queue") / f"{image_path.stem}.json"
        if review_file.exists():
            print(f"\n[E2E] Verifying review file: {review_file}")
            with open(review_file) as f:
                data = json.load(f)
                assert "extraction_trace" in data, (
                    "Review JSON missing extraction_trace"
                )
                assert data["extraction_trace"] is not None
                assert "step1_vat_raw" in data["extraction_trace"]
                print("[E2E] Verified: extraction_trace found in review JSON")

        print("-" * 40)
        raise e
