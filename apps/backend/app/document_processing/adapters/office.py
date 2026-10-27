"""PPTX/DOCX -> Document IR (basic, explicitly limited).

These formats are outside this round's quality guarantee.  They are routed
through the same IR so no second parsing model exists, but the quality report
marks them ``office_limited`` and preserves the legacy parser's warnings.
"""

from __future__ import annotations

from pathlib import Path

from app.document_processing.adapters.pdf import ParseContext
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    SourceSpan,
    TableData,
)
from app.document_processing.normalization.sections import build_sections
from app.parsers.base import ParsedBlock, ParsedDocument, ParsedPage
from app.parsers.document import parse_document


def parse_office(path: Path, context: ParseContext) -> DocumentIR:
    parsed: ParsedDocument = parse_document(path)
    pages: list[PageIR] = []
    global_order = 0
    for raw_page in parsed.pages:
        page = PageIR(
            page_id=f"{context.parse_run_id}-p{raw_page.page_number}",
            page_number=raw_page.page_number,
            extraction="native_text" if raw_page.raw_text.strip() else "none",
            status=_page_status(raw_page),
            text=raw_page.raw_text,
            confidence=raw_page.confidence,
            warnings=[raw_page.warning] if raw_page.warning else [],
        )
        blocks: list[BlockIR] = []
        for raw_block in raw_page.blocks:
            block = _convert_block(raw_block, page.page_number, len(blocks), global_order, context)
            if block is None:
                continue
            blocks.append(block)
            global_order += 1
        page.blocks = blocks
        pages.append(page)

    document = DocumentIR(
        document_id=context.asset_id,
        asset_id=context.asset_id,
        parse_run_id=context.parse_run_id,
        doc_type=parsed.format,
        file_sha256=context.file_sha256,
        parser_name="legacy-office-parser",
        parser_version=parsed.parser_version,
        config_version="office-basic-v1",
        pages=pages,
        warnings=list(parsed.warnings)[:50],
        page_count=len(pages),
    )
    document.sections = build_sections(document, document_title=context.title)
    return document


def _page_status(page: ParsedPage) -> str:
    if page.parse_status == "ocr_candidate":
        return "needs_ocr"
    if page.parse_status == "failed":
        return "failed"
    return "parsed" if page.raw_text.strip() else "empty"


def _convert_block(
    raw: ParsedBlock, page_number: int, order: int, global_order: int, context: ParseContext,
) -> BlockIR | None:
    block_type = raw.block_type
    text = (raw.content or "").strip()
    kind = "paragraph"
    level = 0
    table = None
    figure = None
    warnings: list[str] = [raw.warning] if raw.warning else []
    extraction = raw.extraction_method if raw.extraction_method in {
        "native_text", "ocr", "vision", "heuristic", "mixed", "none"} else "native_text"
    if block_type in {"title", "heading"}:
        kind = "heading"
        level = 1 if page_number == 1 and order == 0 else 2
    elif block_type == "table":
        rows = [line.split(" | ") for line in text.splitlines() if line.strip()]
        if rows:
            table = TableData(rows=rows, header_rows=1)
            kind = "table"
            warnings.append("PPTX/DOCX 表格由旧解析器压平，行列结构可能不完整")
        else:
            kind = "paragraph"
    elif block_type in {"image", "image_or_object"}:
        kind = "figure"
        figure = FigureData(kind="other", description=None, uncertain=True)
        warnings.append("PPTX/DOCX 内嵌图片/公式/图表未做视觉识别")
        extraction = "none"
    elif block_type == "list":
        kind = "list"
    if not text and kind not in {"figure", "table"}:
        return None
    return BlockIR(
        block_id=f"{context.parse_run_id[:8]}-p{page_number}-b{order + 1}",
        page_number=page_number,
        order=order,
        global_order=global_order,
        type=kind,
        level=level,
        text=text or ("表格" if kind == "table" else "图片/对象"),
        table=table,
        figure=figure,
        bbox=None,
        source=SourceSpan(asset_id=context.asset_id, page_number=page_number,
                          location_label=raw.location_label),
        extraction=extraction,
        confidence=raw.confidence,
        warnings=warnings[:8],
    )
