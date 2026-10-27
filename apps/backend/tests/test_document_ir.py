"""Document IR contract, sections, chunks, markdown and quality rules."""

from __future__ import annotations

import json

import pytest

from app.document_processing.chunking import build_chunks
from app.document_processing.engines.pdf_text import EngineInfo
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    IRValidationError,
    PageIR,
    SourceSpan,
    TableData,
)
from app.document_processing.normalization.markdown import render_markdown
from app.document_processing.normalization.sections import build_sections
from app.document_processing.quality import EngineState, assess
from tests.notebook_fixtures import simple_ir


def _engines(*, ocr: bool = False, vision: bool = False) -> EngineState:
    return EngineState(
        ocr=EngineInfo(name="ocr", version="1", available=ocr),
        vision=EngineInfo(name="vision", version="1", available=vision),
    )


def test_ir_roundtrip_and_fingerprint_are_stable():
    document = simple_ir("asset-1", "run-12345678")
    document.seal()
    payload = document.to_dict()
    restored = DocumentIR.from_dict(json.loads(json.dumps(payload, ensure_ascii=False)))
    assert restored.fingerprint == document.fingerprint
    assert restored.document_id == document.document_id
    assert restored.sections[0].block_ids == document.sections[0].block_ids
    assert restored.compute_fingerprint() == document.fingerprint


def test_fingerprint_changes_when_text_changes():
    document = simple_ir("asset-1", "run-12345678")
    document.seal()
    first = document.fingerprint
    document.pages[0].blocks[-1].text = "不同的内容"
    document.seal()
    assert document.fingerprint != first


def test_validation_rejects_unknown_section_block_and_duplicate_ids():
    document = simple_ir("asset-1", "run-12345678")
    document.sections[0].block_ids.append("missing-block")
    with pytest.raises(IRValidationError):
        document.seal()


def test_sections_group_across_pages_and_ignore_running_headers():
    pages = []
    for page_number, text in ((1, "第一章 函数"), (2, "第一章 函数")):
        blocks = [BlockIR(
            block_id=f"p{page_number}-h1", page_number=page_number, order=0,
            global_order=page_number * 10, type="heading", level=1, text=text,
            source=SourceSpan(asset_id="a", page_number=page_number),
        )]
        blocks.append(BlockIR(
            block_id=f"p{page_number}-b1", page_number=page_number, order=1,
            global_order=page_number * 10 + 1, type="paragraph",
            text=f"第 {page_number} 页正文",
            source=SourceSpan(asset_id="a", page_number=page_number),
        ))
        pages.append(PageIR(
            page_id=f"p{page_number}", page_number=page_number, text="第一章 函数\n正文",
            status="parsed", extraction="native_text", blocks=blocks,
        ))
    document = DocumentIR(
        document_id="a", asset_id="a", parse_run_id="run-12345678", doc_type="pdf",
        page_count=2, pages=pages,
    )
    sections = build_sections(document, document_title="资料")
    assert len(sections) == 1
    assert sections[0].page_start == 1
    assert sections[0].page_end == 2
    assert len(sections[0].block_ids) == 4


def test_sections_split_oversized_unstructured_document():
    blocks = [
        BlockIR(
            block_id=f"p1-b{index}", page_number=1, order=index, global_order=index,
            type="paragraph", text=("内容" * 500) + str(index),
            source=SourceSpan(asset_id="a", page_number=1),
        )
        for index in range(10)
    ]
    document = DocumentIR(
        document_id="a", asset_id="a", parse_run_id="run-123", doc_type="pdf",
        page_count=1,
        pages=[PageIR(page_id="p1", page_number=1, status="parsed",
                      extraction="native_text", blocks=blocks)],
    )
    sections = build_sections(document, document_title="资料")
    assert len(sections) > 1
    assert sections[0].title == "资料"
    assert sections[1].title.startswith("第 2 部分")


def test_chunks_follow_sections_and_keep_page_provenance():
    document = simple_ir(
        "asset-1", "run-12345678",
        sections=[("第一章", ["甲" * 900, "乙" * 900]), ("第二章", ["丙" * 50])],
    )
    chunks = build_chunks(document)
    assert len(chunks) >= 3
    assert chunks[0].text.startswith("【第一章】")
    assert chunks[-1].section_id == document.sections[-1].section_id
    assert all(chunk.page_numbers == [1] for chunk in chunks)


def test_markdown_renders_table_math_and_figure_placeholder():
    document = simple_ir("asset-1", "run-12345678")
    page = document.pages[0]
    page.blocks.append(BlockIR(
        block_id="run-1234-table", page_number=1, order=9, global_order=9,
        type="table", text="x | f(x)\n0 | 1",
        table=TableData(rows=[["x", "f(x)"], ["0", "1"]], header_rows=1),
        source=SourceSpan(asset_id="asset-1", page_number=1),
    ))
    page.blocks.append(BlockIR(
        block_id="run-1234-math", page_number=1, order=10, global_order=10,
        type="equation", text="lim", latex="\\lim_{x\\to 0} f(x)",
        source=SourceSpan(asset_id="asset-1", page_number=1),
    ))
    markdown = render_markdown(document)
    assert "| x | f(x) |" in markdown
    assert "$$" in markdown and "\\lim" in markdown
    assert "<!-- page:1 -->" in markdown


def test_quality_complete_when_text_and_structure_exist():
    document = simple_ir("asset-1", "run-12345678")
    quality = assess(document, engines=_engines(), doc_type="pdf")
    assert quality.status == "complete"
    assert quality.generation_allowed is True
    assert quality.text_chars > 0
    assert quality.usable_page_ranges == [[1, 1]]


def test_quality_blocks_generation_when_no_text_and_ocr_missing():
    page = PageIR(
        page_id="p1", page_number=1, status="needs_ocr", extraction="none",
        text="", warnings=["没有文字层"],
    )
    document = DocumentIR(
        document_id="a", asset_id="a", parse_run_id="run-123", doc_type="pdf",
        page_count=1, pages=[page],
    )
    quality = assess(document, engines=_engines(ocr=False), doc_type="pdf")
    assert quality.status == "needs_ocr"
    assert quality.generation_allowed is False
    assert "OCR" in (quality.generation_block_reason or "")
    assert any(issue.code == "ocr_required" for issue in quality.issues)


def test_quality_partial_when_one_of_two_pages_is_empty():
    good = PageIR(page_id="p1", page_number=1, status="parsed", extraction="native_text",
                  text="有内容的正文" * 60, confidence=1.0,
                  blocks=[BlockIR(
                      block_id="p1-b1", page_number=1, order=0, global_order=0,
                      type="paragraph", text="有内容的正文" * 60,
                      source=SourceSpan(asset_id="a", page_number=1),
                  )])
    bad = PageIR(page_id="p2", page_number=2, status="empty", extraction="none", text="")
    document = DocumentIR(
        document_id="a", asset_id="a", parse_run_id="run-123", doc_type="pdf",
        page_count=2, pages=[good, bad],
    )
    quality = assess(document, engines=_engines(), doc_type="pdf")
    assert quality.status == "partial"
    assert quality.generation_allowed is True


def test_quality_marks_office_documents_as_limited():
    document = simple_ir("asset-1", "run-12345678", doc_type="pptx")
    document.parser_name = "legacy-office-parser"
    quality = assess(document, engines=_engines(), doc_type="pptx")
    assert any(issue.code == "office_limited" for issue in quality.issues)
    assert quality.status == "partial"


def test_quality_fails_below_minimum_text():
    page = PageIR(
        page_id="p1", page_number=1, status="parsed", extraction="native_text",
        text="太短", blocks=[BlockIR(
            block_id="p1-b1", page_number=1, order=0, global_order=0,
            type="paragraph", text="太短",
            source=SourceSpan(asset_id="a", page_number=1),
        )],
    )
    document = DocumentIR(
        document_id="a", asset_id="a", parse_run_id="run-123", doc_type="pdf",
        page_count=1, pages=[page],
    )
    quality = assess(document, engines=_engines(), doc_type="pdf")
    assert quality.status == "failed"
    assert quality.generation_allowed is False
