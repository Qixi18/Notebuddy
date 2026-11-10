"""Synthetic completeness, layout and scale regressions for the CPU standard route."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import weakref
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.document_processing.adapters.pdf import ParseContext, parse_pdf
from app.document_processing.engines.ocr import OcrLine, OcrResult
from app.document_processing.engines.pdf_text import EngineInfo
from app.document_processing.ir import BlockIR, DocumentIR, PageIR, TableData
from app.document_processing.normalization.sections import build_sections
from app.document_processing.quality import EngineState, assess
from app.generation.composer import compose_offline
from app.generation.context import _block_payload
from app.generation.planner import build_plan


def _block(text, *, block_id="source", kind="paragraph", table=None):
    return BlockIR(block_id=block_id, page_number=1, order=0, global_order=0,
                   type=kind, text=text, table=table)


def _document(blocks):
    return DocumentIR(document_id="asset", asset_id="asset", parse_run_id="run",
                      doc_type="pdf", pages=[PageIR(page_id="p1", page_number=1, blocks=blocks)])


def _quality(document):
    return assess(document, doc_type="pdf", engines=EngineState(
        ocr=EngineInfo("test", "1", False), vision=EngineInfo("test", "1", False)))


def test_standard_snapshot_retains_long_text_and_all_table_cells():
    text = "source content " * 700 + "UNIQUE_TEXT_TAIL"
    rows = [[f"cell-{row}-{col}-" + "value " * 20 for col in range(14)] for row in range(45)]
    rows[-1][-1] = "UNIQUE_TABLE_TAIL"
    payload = _block_payload(_block(text))
    assert payload["text"] == text
    table = _block_payload(_block("\n".join(" | ".join(row) for row in rows),
                                 kind="table", table=TableData(rows=rows, header_rows=1)))
    assert table["table"]["rows"] == rows
    assert table["text"].endswith("UNIQUE_TABLE_TAIL")


def test_table_ir_roundtrip_keeps_cells_larger_than_two_thousand_characters():
    table = TableData(rows=[["header"], ["cell content " * 500 + "CELL_TAIL"]], header_rows=1)
    assert TableData.from_dict(table.to_dict()).rows == table.rows


def test_offline_generation_does_not_cut_a_long_source_paragraph():
    text = "source content " * 2_000 + "UNIQUE_TEXT_TAIL"
    snapshot = {"generator": "offline-extractive", "batch_chars": 18_000,
        "current_document": {"type": "doc", "content": []}, "sources": [{
            "asset_id": "asset", "name": "long.pdf", "parse_run_id": "run",
            "sections": [{"section_id": "section", "title": "Long source", "level": 1,
                          "page_start": 1, "page_end": 1, "blocks": [_block_payload(_block(text))]}]}]}
    plan = build_plan(snapshot)
    result = compose_offline(snapshot, plan, [unit["unit_id"] for unit in plan["units"]])
    paragraphs = [node for node in result.nodes if node["type"] == "paragraph"]
    output = "".join(child["text"] for node in paragraphs for child in node.get("content", []))
    assert output == text
    assert all(refs == ["source"] for refs in result.source_map.values())


def test_sections_keep_all_sources_beyond_four_hundred_headings():
    blocks = [_block(f"Chapter {index}", block_id=f"heading-{index}", kind="heading")
              for index in range(450)]
    document = _document(blocks)
    sections = build_sections(document)
    assert {block for section in sections for block in section.block_ids} == {
        block.block_id for block in blocks}
    assert len(sections) <= 400


def test_standard_ir_splits_long_text_and_tables_without_losing_sources():
    from app.document_processing.normalization.blocks import normalize_standard_blocks

    text = "0123456789" * 2_000 + "TAIL"
    rows = [[f"row-{r}-col-{c}" for c in range(14)] for r in range(90)]
    document = _document([_block(text), _block("", block_id="table", kind="table",
                                              table=TableData(rows=rows, header_rows=1))])
    normalize_standard_blocks(document)
    texts = [block for block in document.all_blocks() if block.type == "paragraph"]
    tables = [block.table for block in document.all_blocks() if block.type == "table"]
    assert "".join(block.text for block in texts) == text
    assert all(len(block.text) <= 2_000 for block in texts)
    assert len({block.block_id for block in document.all_blocks()}) == len(list(document.all_blocks()))
    assert all(table.rows[0] == rows[0] for table in tables)
    assert [row for table in tables for row in table.rows[1:]] == rows[1:]
    assert all(len(row) == 14 for table in tables for row in table.rows)
    before = [block.to_dict() for block in document.all_blocks()]
    normalize_standard_blocks(document)
    assert [block.to_dict() for block in document.all_blocks()] == before


def _scan_with_footer(path):
    image = Image.new("RGB", (1100, 1400), "white")
    ImageDraw.Draw(image).text((50, 200), "MAIN SCANNED CONTENT", fill="black", font_size=38)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_image(pymupdf.Rect(0, 0, 600, 760), stream=encoded.getvalue())
        page.insert_text((300, 785), "1", fontsize=9)
        pdf.save(path)


def _store(tmp_path):
    def store(page, data):
        name = f"page-{page}.png"
        (tmp_path / name).write_bytes(data)
        return name
    return store


def test_scan_with_native_footer_still_runs_ocr(tmp_path):
    path = tmp_path / "mixed.pdf"
    _scan_with_footer(path)
    calls = []
    def recognize(image, **kwargs):
        calls.append(image)
        return OcrResult(lines=[OcrLine("MAIN SCANNED CONTENT", confidence=.99)])
    document = parse_pdf(path, ParseContext("asset", "run"), render_store=_store(tmp_path),
        ocr_available=True, vision_available=False, ocr_recognize=recognize)
    assert len(calls) == 1
    assert "MAIN SCANNED CONTENT" in document.pages[0].text
    assert document.pages[0].extraction == "ocr"


def test_scan_with_footer_and_no_ocr_is_blocked(tmp_path):
    path = tmp_path / "mixed.pdf"
    _scan_with_footer(path)
    document = parse_pdf(path, ParseContext("asset", "run"),
                         ocr_available=False, vision_available=False)
    assert document.pages[0].status == "needs_ocr"
    assert not _quality(document).generation_allowed


def test_vector_diagram_keeps_citable_image_and_quality_warning(tmp_path):
    path = tmp_path / "vector.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((40, 40), "Signal diagram", fontsize=14)
        page.draw_circle((150, 240), 45)
        page.draw_circle((400, 240), 45)
        page.draw_line((195, 240), (355, 240))
        pdf.save(path)
    def figure_store(page, data, suffix):
        name = f"figure-{len(list(tmp_path.glob('figure-*')))}{suffix}"
        (tmp_path / name).write_bytes(data)
        return name
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False,
                         vision_available=False, figure_store=figure_store)
    figures = [block for block in document.all_blocks() if block.figure]
    assert figures and all(block.figure.image_key for block in figures)
    assert all((tmp_path / block.figure.image_key).exists() for block in figures)
    assert _quality(document).status == "partial"
    assert "figure_not_interpreted" in {issue.code for issue in _quality(document).issues}


def test_small_vector_detail_is_not_filtered_as_a_bitmap_logo(tmp_path):
    path = tmp_path / "small-vector.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((40, 40), "Circuit detail")
        page.draw_circle((150, 250), 15)
        pdf.save(path)
    def store(page, data, suffix):
        name = f"detail{suffix}"
        (tmp_path / name).write_bytes(data)
        return name
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False,
                         vision_available=False, figure_store=store)
    assert any(block.figure and block.figure.image_key for block in document.all_blocks())


@pytest.mark.parametrize("spanning_title", [False, True])
def test_two_columns_are_read_down_each_column(tmp_path, spanning_title):
    path = tmp_path / "columns.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        if spanning_title:
            page.insert_text((40, 35), "A full width title across both columns of this document", fontsize=19)
        for x, y, text in [(40, 80, "LEFT ONE premise"), (330, 80, "RIGHT ONE result"),
                           (40, 145, "LEFT TWO derivation"), (330, 145, "RIGHT TWO conclusion")]:
            page.insert_text((x, y), text, fontsize=12)
        pdf.save(path)
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False, vision_available=False)
    text = "\n".join(block.text for block in document.all_blocks())
    assert text.index("LEFT ONE") < text.index("LEFT TWO") < text.index("RIGHT ONE") < text.index("RIGHT TWO")
    if spanning_title:
        assert text.index("full width title") < text.index("LEFT ONE")


def test_standard_pdf_uses_page_iterator_not_page_collector(tmp_path, monkeypatch):
    from app.document_processing.engines import pdf_text

    path = tmp_path / "many-pages.pdf"
    with pymupdf.open() as pdf:
        for number in range(60):
            pdf.new_page().insert_text((40, 80), f"PAGE {number} preserved source content")
        pdf.save(path)
    monkeypatch.setattr(pdf_text, "extract_pdf", lambda *args, **kwargs: pytest.fail("collected all raw pages"))
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False, vision_available=False)
    assert len(document.pages) == 60
    assert "PAGE 59" in document.pages[-1].text


def test_standard_defaults_and_explicit_limits():
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    env.pop("NOTEBOOK_MAX_UPLOAD_MB", None)
    env.pop("NOTEBOOK_MAX_PAGES", None)
    script = ("import json; from app.core.config import settings; "
              "print(json.dumps([settings.max_upload_bytes, settings.max_pages]))")
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=env,
                            capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == [200 * 1024 * 1024, 2_000]
    env.update(NOTEBOOK_MAX_UPLOAD_MB="80", NOTEBOOK_MAX_PAGES="700")
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=env,
                            capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == [80 * 1024 * 1024, 700]


def test_large_page_render_is_bounded_before_pixmap_allocation():
    from app.document_processing.engines import pdf_text

    calls = []
    def pixmap(**kwargs):
        calls.append(kwargs)
        assert 10_000 * kwargs["dpi"] / 72 <= pdf_text.MAX_RENDER_SIDE
        return SimpleNamespace(tobytes=lambda _: b"png")
    page = SimpleNamespace(rect=SimpleNamespace(width=10_000, height=8_000), get_pixmap=pixmap)
    assert pdf_text._render(page, 120) == b"png"
    assert len(calls) == 1


def test_vector_table_borders_are_not_duplicate_figures(tmp_path):
    path = tmp_path / "grid.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        for x in (50, 250, 450):
            page.draw_line((x, 100), (x, 220))
        for y in (100, 140, 180, 220):
            page.draw_line((50, y), (450, y))
        for index, (x, y) in enumerate([(60, 125), (260, 125), (60, 165), (260, 165)]):
            page.insert_text((x, y), f"value-{index}")
        pdf.save(path)
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False, vision_available=False)
    assert any(block.table for block in document.all_blocks())
    assert not any(block.figure for block in document.all_blocks())


def test_raw_scan_pages_are_consumed_without_retaining_all_renders(tmp_path, monkeypatch):
    from app.document_processing.engines import pdf_text

    refs, counts = [], []
    def pages(*args, **kwargs):
        for number in range(1, 31):
            page = pdf_text.RawPage(page_number=number, render_png=b"synthetic-png")
            refs.append(weakref.ref(page))
            counts.append(sum(ref() is not None for ref in refs))
            yield page
    monkeypatch.setattr(pdf_text, "iter_pdf_pages", pages)
    document = parse_pdf(tmp_path / "unused.pdf", ParseContext("asset", "run"),
        render_store=lambda page, data: f"page-{page}.png", ocr_available=True,
        vision_available=False, ocr_recognize=lambda *args, **kwargs: OcrResult(
            lines=[OcrLine("Scanned page source", confidence=.99)]))
    assert len(document.pages) == 30
    assert max(counts) <= 2


def test_two_scanned_halves_with_footer_do_not_bypass_ocr(tmp_path):
    path = tmp_path / "split-scan.pdf"
    image = Image.new("RGB", (600, 380), "white")
    ImageDraw.Draw(image).text((30, 60), "Scanned body", fill="black", font_size=30)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        for y in (0, 380):
            page.insert_image(pymupdf.Rect(0, y, 600, y + 380), stream=buffer.getvalue())
        page.insert_text((300, 785), "1", fontsize=9)
        pdf.save(path)
    calls = []
    def recognize(image, **kwargs):
        calls.append(image)
        return OcrResult(lines=[OcrLine("Scanned body", confidence=.99)])
    document = parse_pdf(path, ParseContext("asset", "run"), render_store=_store(tmp_path),
        ocr_available=True, vision_available=False, ocr_recognize=recognize)
    assert len(calls) == 1
    assert "Scanned body" in document.pages[0].text


def test_short_centered_spanning_title_does_not_join_columns(tmp_path):
    path = tmp_path / "short-title.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((180, 35), "Short centered title", fontsize=17)
        for x, y, text in [(40, 90, "LEFT ONE " + "body " * 5),
                           (330, 90, "RIGHT ONE " + "body " * 5),
                           (40, 150, "LEFT TWO " + "body " * 5),
                           (330, 150, "RIGHT TWO " + "body " * 5)]:
            page.insert_text((x, y), text, fontsize=11)
        pdf.save(path)
    document = parse_pdf(path, ParseContext("asset", "run"), ocr_available=False, vision_available=False)
    text = "\n".join(block.text for block in document.all_blocks())
    assert text.index("LEFT ONE") < text.index("LEFT TWO") < text.index("RIGHT ONE")


def test_extreme_page_size_is_rejected_before_oversized_allocation():
    from app.document_processing.engines import pdf_text

    calls = []
    def pixmap(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(tobytes=lambda _: b"png")
    page = SimpleNamespace(rect=SimpleNamespace(width=1_000_000, height=1_000_000), get_pixmap=pixmap)
    # Below 1 dpi is not supported by this path; fail explicitly without an allocation.
    assert pdf_text._render(page, 120) is None
    assert not calls
