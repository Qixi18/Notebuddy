import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.document_processing.adapters.pdf import ParseContext, parse_pdf
from app.document_processing.engines import pdf_text
from app.document_processing.engines.ocr import OcrLine, OcrResult


def _scan_image() -> Image.Image:
    from PIL import ImageFont

    image = Image.new("RGB", (1200, 320), "white")
    font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", 58)
    ImageDraw.Draw(image).text((40, 80), "极限的定义 Limit", fill="black", font=font)
    return image


def _scanned_pdf(path: Path) -> None:
    image = _scan_image()
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", quality=95)
    payload = encoded.getvalue()
    content = b"q 500 0 0 160 0 0 cm /Im0 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 160] "
         b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"),
        b"<< /Type /XObject /Subtype /Image /Width 1000 /Height 320 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
        + str(len(payload)).encode() + b" >>\nstream\n" + payload + b"\nendstream",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def test_pdfium_renders_scanned_pdf_without_pymupdf(monkeypatch, tmp_path):
    pytest.importorskip("pypdfium2")
    monkeypatch.setattr(pdf_text, "_pymupdf", lambda: None)
    path = tmp_path / "scan.pdf"
    _scanned_pdf(path)
    stored: dict[int, bytes] = {}

    def store(page_number: int, png: bytes) -> str:
        stored[page_number] = png
        return f"derived/pages/p{page_number}.png"

    def recognize(_png, **_kwargs):
        return OcrResult(lines=[OcrLine("扫描页面 OCR 内容", [10, 20, 200, 50], 0.96)],
                         engine="test", version="1")

    document = parse_pdf(
        path,
        ParseContext(asset_id="asset-1", parse_run_id="run-1", doc_type="pdf"),
        render_store=store, ocr_available=True, vision_available=False,
        ocr_recognize=recognize,
    )

    page = document.pages[0]
    assert page.extraction == "ocr"
    assert page.status == "parsed"
    assert "扫描页面" in page.text
    assert page.confidence == 0.96
    assert page.blocks[0].bbox == [10, 20, 200, 50]
    assert page.render_key == "derived/pages/p1.png"
    assert stored[1].startswith(b"\x89PNG\r\n\x1a\n")


def test_pdfium_render_error_keeps_failed_page(monkeypatch, tmp_path):
    pytest.importorskip("pypdfium2")
    monkeypatch.setattr(pdf_text, "_pymupdf", lambda: None)
    path = tmp_path / "scan.pdf"
    _scanned_pdf(path)
    monkeypatch.setitem(sys.modules, "pypdfium2", None)

    document = parse_pdf(
        path,
        ParseContext(asset_id="asset-1", parse_run_id="run-1", doc_type="pdf"),
        render_store=lambda *_: "unused", ocr_available=True, vision_available=False,
        ocr_recognize=lambda *_args, **_kwargs: OcrResult(),
    )

    assert len(document.pages) == 1
    assert document.pages[0].status == "failed"
    assert any("PDFium" in warning
               for warning in document.pages[0].warnings)


@pytest.mark.skipif(os.getenv("NOTEBOOK_RUN_REAL_OCR") != "1",
                    reason="set NOTEBOOK_RUN_REAL_OCR=1 to run local OCR model integration")
def test_real_rapidocr_reads_scanned_pdf_without_pymupdf(monkeypatch, tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    pytest.importorskip("pypdfium2")
    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "rapidocr")
    monkeypatch.setattr(pdf_text, "_pymupdf", lambda: None)
    path = tmp_path / "scan-chinese.pdf"
    _scanned_pdf(path)

    document = parse_pdf(
        path,
        ParseContext(asset_id="asset-real-ocr", parse_run_id="run-real-ocr", doc_type="pdf"),
        render_store=lambda page_number, _png: f"derived/pages/p{page_number}.png",
    )

    page = document.pages[0]
    assert page.status in {"parsed", "partial"}, page.warnings
    assert "极限" in page.text, page.text
    assert page.confidence is not None and page.confidence > 0.5
    assert page.blocks[0].bbox is not None


@pytest.mark.skipif(os.getenv("NOTEBOOK_RUN_REAL_OCR") != "1",
                    reason="set NOTEBOOK_RUN_REAL_OCR=1 to run local OCR model integration")
@pytest.mark.parametrize("extension", [".png", ".jpg"])
def test_real_rapidocr_reads_uploaded_image(monkeypatch, tmp_path, extension):
    from app.document_processing.adapters.image import parse_image

    pytest.importorskip("rapidocr_onnxruntime")
    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "rapidocr")
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "native")
    path = tmp_path / f"scan{extension}"
    if extension == ".jpg":
        _scan_image().save(path, quality=95)
    else:
        _scan_image().save(path)

    document = parse_image(
        path,
        ParseContext(asset_id="asset-real-image", parse_run_id="run-real-image", doc_type="image"),
        vision_available=False,
    )

    page = document.pages[0]
    assert page.status == "parsed", page.warnings
    assert "极限" in page.text, page.text
    assert page.confidence is not None and page.confidence > 0.5
    assert page.blocks[0].bbox is not None
