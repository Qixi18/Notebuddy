"""PDF/image adapters: native text, scanned pages, OCR fallback, honesty."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.document_processing.adapters.image import parse_image
from app.document_processing.adapters.pdf import ParseContext, parse_pdf
from app.document_processing.engines.ocr import OcrLine, OcrResult

pymupdf = pytest.importorskip("pymupdf")


def _text_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Chapter 1 Limits", fontsize=22)
    page.insert_text((72, 130), "The limit of f(x) as x approaches a is L.", fontsize=11)
    page.insert_text((72, 150), "It is written as lim f(x) = L.", fontsize=11)
    page.insert_text((72, 190), "Definition", fontsize=16)
    page.insert_text((72, 220), "A function has a limit when values approach L.", fontsize=11)
    document.save(str(path))
    document.close()


def _scanned_pdf(path: Path) -> None:
    image = Image.new("RGB", (600, 800), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(str(path))
    document.close()


def _illustrated_pdf(path: Path) -> bytes:
    image = Image.new("RGB", (160, 120), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Chapter 1 Limits", fontsize=22)
    page.insert_text((72, 130), "The limit of f(x) as x approaches a is L.", fontsize=11)
    page.insert_image(pymupdf.Rect(72, 180, 232, 300), stream=image_bytes)
    document.save(str(path))
    document.close()
    return image_bytes


def _fake_ocr(*_args, **_kwargs) -> OcrResult:
    return OcrResult(
        lines=[
            OcrLine(text="Chapter 1 Limits", bbox=[50, 50, 300, 80], confidence=0.92),
            OcrLine(text="The limit of f(x) is L.", bbox=[50, 90, 400, 110], confidence=0.9),
            OcrLine(text="lim f(x) = L", bbox=[50, 120, 250, 140], confidence=0.85),
        ],
        engine="fake", version="1", warnings=["OCR 识别结果请核对"],
    )


class _FakeVision:
    def __init__(self) -> None:
        self.unavailable = False

    def __call__(self, *_args, **_kwargs):
        return type("Vision", (), {
            "description": "流程图：输入经过判断节点后输出",
            "latex": "\\int_0^1 x dx = 1/2",
            "table": {"rows": [["x", "y"], ["1", "2"]], "header_rows": 1},
            "figure": {"kind": "diagram", "nodes": ["输入", "判断", "输出"],
                       "edges": ["输入 -> 判断", "判断 -> 输出"]},
            "uncertain": False,
            "warnings": [],
        })()


def _context(asset_id: str = "asset-1") -> ParseContext:
    return ParseContext(asset_id=asset_id, parse_run_id="run-12345678", doc_type="pdf",
                        title="资料")


def _store(tmp_path: Path):
    def store(page_number: int, png: bytes) -> str:
        path = tmp_path / f"p{page_number}.png"
        path.write_bytes(png)
        return f"derived/pages/p{page_number}.png"

    return store


def test_native_text_pdf_builds_blocks_and_headings(tmp_path):
    path = tmp_path / "text.pdf"
    _text_pdf(path)
    document = parse_pdf(path, _context(), ocr_available=False, vision_available=False)
    blocks = [block for page in document.pages for block in page.blocks]
    assert document.pages[0].extraction == "native_text"
    assert any(block.type == "heading" for block in blocks)
    assert "limit of f(x)" in document.pages[0].text
    assert document.parser_name == "pymupdf"


def test_scanned_pdf_without_ocr_is_marked_needs_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    _scanned_pdf(path)
    document = parse_pdf(path, _context(), ocr_available=False, vision_available=False)
    page = document.pages[0]
    assert page.status == "needs_ocr"
    assert page.extraction == "none"
    assert page.text.strip() == ""
    assert any("OCR" in warning for warning in page.warnings)


def test_scanned_pdf_uses_ocr_when_available(tmp_path):
    path = tmp_path / "scan.pdf"
    _scanned_pdf(path)
    document = parse_pdf(
        path, _context(), render_store=_store(tmp_path),
        ocr_available=True, vision_available=False, ocr_recognize=_fake_ocr,
    )
    page = document.pages[0]
    assert page.extraction == "ocr"
    assert page.status in {"parsed", "partial"}
    assert "Chapter 1 Limits" in page.text
    assert page.render_key
    assert any("lim f(x)" in block.text for block in page.blocks)


def test_scanned_pdf_uses_vision_when_ocr_missing(tmp_path):
    path = tmp_path / "scan.pdf"
    _scanned_pdf(path)
    document = parse_pdf(
        path, _context(), render_store=_store(tmp_path),
        ocr_available=False, vision_available=True, vision_describe=_FakeVision(),
    )
    page = document.pages[0]
    assert page.extraction == "vision"
    assert any(block.type in {"equation", "table", "figure"} for block in page.blocks)


def test_native_pdf_persists_embedded_figure_without_vision(tmp_path):
    path = tmp_path / "illustrated.pdf"
    expected_image = _illustrated_pdf(path)
    stored: list[tuple[int, bytes, str]] = []

    def figure_store(page_number: int, image: bytes, suffix: str) -> str:
        stored.append((page_number, image, suffix))
        return f"derived/figures/asset-1/run-12345678/p{page_number}-figure{suffix}"

    def no_vision(*_args, **_kwargs):
        raise AssertionError("vision should not run when unavailable")

    document = parse_pdf(
        path, _context(), ocr_available=False, vision_available=False,
        figure_store=figure_store, vision_describe=no_vision,
    )

    figures = [block.figure for page in document.pages for block in page.blocks if block.figure]
    assert len(stored) == 1
    assert stored[0][0] == 1
    assert stored[0][2] == ".png"
    with (
        Image.open(io.BytesIO(stored[0][1])) as extracted,
        Image.open(io.BytesIO(expected_image)) as expected,
    ):
        assert extracted.size == expected.size
        assert extracted.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
    assert len(figures) == 1
    assert figures[0].image_key.endswith("p1-figure.png")
    assert figures[0].uncertain is True


def test_image_with_fake_ocr_produces_text_blocks(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (600, 800), "white").save(path)
    document = parse_image(
        path, _context("asset-img"), ocr_available=True, vision_available=False,
        ocr_recognize=_fake_ocr,
    )
    page = document.pages[0]
    assert page.extraction == "ocr"
    assert "Chapter 1 Limits" in page.text
    assert any(block.type == "paragraph" for block in page.blocks)


def test_image_uses_vision_for_table_equation_and_figure(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (600, 800), "white").save(path)
    document = parse_image(
        path, _context("asset-img"), ocr_available=False, vision_available=True,
        vision_describe=_FakeVision(),
    )
    types = {block.type for block in document.pages[0].blocks}
    assert {"table", "equation", "figure"}.issubset(types)
    original_key = next(block.figure.image_key for block in document.pages[0].blocks
                        if block.figure and block.figure.image_key)
    assert original_key.startswith("derived/figures/asset-img/run-12345678/")
    assert (settings.data_dir / original_key).is_file()


def test_webp_uses_matching_vision_mime_and_preserves_source(tmp_path, monkeypatch):
    path = tmp_path / "page.webp"
    Image.new("RGB", (120, 90), "white").save(path, format="WEBP")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source = path.read_bytes()
    seen = []

    def vision(image, *, mime):
        seen.append((image, mime))
        return _FakeVision()()

    document = parse_image(
        path, _context("asset-webp"), ocr_available=False, vision_available=True,
        vision_describe=vision,
    )
    figure = next(
        block.figure for block in document.pages[0].blocks if block.figure and block.figure.image_key
    )

    assert seen == [(source, "image/webp")]
    evidence = settings.data_dir / figure.image_key
    assert evidence.read_bytes() == source


def test_image_uncertain_vision_results_are_kept_with_review_warning(tmp_path, monkeypatch):
    path = tmp_path / "uncertain.png"
    Image.new("RGB", (120, 90), "white").save(path)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")

    def uncertain(*_args, **_kwargs):
        return type("Vision", (), {
            "description": "可能是流程图", "latex": "x+y", "table": None,
            "figure": {"kind": "diagram", "nodes": ["A"], "edges": []},
            "uncertain": True, "warnings": [],
        })()

    document = parse_image(
        path, _context("asset-img"), ocr_available=False, vision_available=True,
        vision_describe=uncertain,
    )
    blocks = document.pages[0].blocks
    assert any(block.type == "equation" and block.latex == "x+y" for block in blocks)
    figure = next(block for block in blocks if block.figure and block.extraction == "vision")
    assert figure.figure.uncertain is True
    assert any("不确定" in warning for warning in figure.warnings)
    assert figure.figure.image_key


def test_image_without_engines_preserves_image_evidence_and_needs_ocr(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (600, 800), "white").save(path)
    document = parse_image(
        path, _context("asset-img"), ocr_available=False, vision_available=False,
    )
    page = document.pages[0]
    assert page.status == "needs_ocr"
    assert any(block.type == "image" for block in page.blocks)
    assert page.blocks[0].source.asset_id == "asset-img"
    assert page.blocks[0].figure.image_key
    assert (settings.data_dir / page.blocks[0].figure.image_key).is_file()
