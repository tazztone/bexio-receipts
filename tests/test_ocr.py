import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from bexio_receipts.ocr import async_run_ocr, run_paddle_ocr


@patch("bexio_receipts.ocr.PaddleOCR")
def test_run_paddle_ocr(mock_paddle):
    # Mocking PaddleOCR's ocr method
    mock_ocr_instance = mock_paddle.return_value
    mock_ocr_instance.ocr.return_value = [
        [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], ("COOP", 0.99)],
            [[[0, 20], [10, 20], [10, 30], [0, 30]], ("Total 10.80", 0.95)],
        ]
    ]

    raw_text, avg_confidence, lines = run_paddle_ocr("dummy_path.png")

    assert "COOP" in raw_text
    assert "Total 10.80" in raw_text
    assert avg_confidence == (0.99 + 0.95) / 2
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_async_run_ocr_paddle(test_settings):
    test_settings.ocr_engine = "paddleocr"
    with patch("bexio_receipts.ocr.run_paddle_ocr") as mock_paddle:
        mock_paddle.return_value = ("Paddle Text", 0.9, [])
        raw_text, conf, _ = await async_run_ocr("path.png", test_settings)
        assert raw_text == "Paddle Text"
        mock_paddle.assert_called_once()


@pytest.mark.asyncio
async def test_async_run_ocr_glm(test_settings):
    test_settings.ocr_engine = "glm-ocr"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "GLM Text"}}
    mock_resp.raise_for_status = MagicMock()

    # Patch Image.open so PIL never touches the fake path, then patch builtins.open
    # so the file-read for base64 encoding also returns controlled bytes.
    mock_img = MagicMock()
    mock_img.size = (100, 100)
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=mock_file)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_file.read.return_value = b"fake-image-bytes"

    with patch("bexio_receipts.ocr.Image.open", return_value=mock_img):
        with patch("bexio_receipts.ocr._optimize_image", side_effect=lambda x: x):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp
                with patch("builtins.open", return_value=mock_file):
                    raw_text, conf, _ = await async_run_ocr("path.png", test_settings)
                    assert raw_text == "GLM Text"
                    assert conf == 0.5
                    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_async_run_ocr_pdf(test_settings):
    test_settings.ocr_engine = "glm-ocr"

    with patch("bexio_receipts.ocr.extract_pdf_text") as mock_extract:
        mock_extract.return_value = "Extracted PDF Text"
        with patch("mimetypes.guess_type", return_value=("application/pdf", None)):
            raw_text, conf, _ = await async_run_ocr("path.pdf", test_settings)
            assert raw_text == "Extracted PDF Text"
            assert conf == 1.0
            mock_extract.assert_called_once()


def test_optimize_image():
    from PIL import Image
    from bexio_receipts.ocr import _optimize_image

    img = Image.new("RGB", (3000, 1000), color="red")
    optimized = _optimize_image(img, max_long_edge=2000)
    assert optimized.size[0] == 2000
    assert optimized.size[1] == 666


def test_extract_pdf_text_success(tmp_path):
    from bexio_receipts.ocr import extract_pdf_text

    pdf_file = tmp_path / "test.pdf"
    pdf_file.touch()

    with patch("pdfplumber.open") as mock_open:
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "This is a long enough text for PDF extraction."
        )
        mock_pdf.pages = [mock_page]
        mock_open.return_value.__enter__.return_value = mock_pdf

        text = extract_pdf_text(str(pdf_file))
        assert text == "This is a long enough text for PDF extraction."


def test_extract_pdf_text_failure(tmp_path):
    from bexio_receipts.ocr import extract_pdf_text

    pdf_file = tmp_path / "test.pdf"
    pdf_file.touch()

    with patch("pdfplumber.open", side_effect=Exception("PDF Error")):
        text = extract_pdf_text(str(pdf_file))
        assert text is None
