"""Optional local MinerU adapter for the NoteBuddy document IR.

MinerU owns layout analysis, OCR, tables, equations, and document-specific
normalization.  This adapter translates its public Content List V2 output into
NoteBuddy's existing IR so downstream quality checks and generation stay the
same.  MinerU remains an optional dependency and is never contacted remotely.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

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


class MinerUUnavailable(RuntimeError):
    """The optional MinerU package is not installed or cannot be imported."""


def availability() -> dict[str, Any]:
    """Return capability information without loading models or downloading files."""
    try:
        available = importlib.util.find_spec("mineru") is not None
    except (ImportError, ValueError):
        available = False
    try:
        version = importlib.metadata.version("mineru") if available else "0"
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return {
        "name": "mineru",
        "version": version,
        "available": available,
        "local_only": True,
        "reason": None if available else "未安装可选依赖 MinerU",
    }


def configured() -> bool:
    return (os.getenv("NOTEBOOK_DOCUMENT_PARSER", "native").strip().lower() == "mineru")


def parse_document(path: Path, context: ParseContext) -> DocumentIR:
    """Parse one local file with MinerU and translate its page blocks to NoteBuddy IR."""
    try:
        from mineru import parse as mineru_parse
        from mineru.render import render
        from mineru.render.contracts import RenderFormat
    except Exception as exc:
        raise MinerUUnavailable(
            "MinerU 未安装或其运行依赖不完整；请检查独立解析环境"
        ) from exc

    tier = (os.getenv("NOTEBOOK_MINERU_TIER", "standard").strip().lower() or "standard")
    if tier not in {"flash", "basic", "standard", "advanced"}:
        raise ValueError("NOTEBOOK_MINERU_TIER 必须是 flash、basic、standard 或 advanced")

    parsed = mineru_parse(
        path,
        tier=tier,
        ocr_mode="auto",
        image_analysis=os.getenv("NOTEBOOK_MINERU_IMAGE_ANALYSIS", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    pages_content = render(parsed.middle_json, RenderFormat.CONTENT_LIST_V2)
    page_infos = list(getattr(parsed.middle_json, "pages", []) or [])
    version = availability()["version"]
    run_prefix = context.parse_run_id[:8]
    pages: list[PageIR] = []
    global_order = 0

    for index, items in enumerate(pages_content):
        info = page_infos[index] if index < len(page_infos) else None
        page_number = int(getattr(info, "page_idx", index)) + 1
        page = PageIR(
            page_id=f"{context.parse_run_id}-p{page_number}",
            page_number=page_number,
            extraction="mineru",
            status="parsed",
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            mapped = _map_item(
                item,
                block_id=f"{run_prefix}-p{page_number}-b{len(page.blocks) + 1}",
                page_number=page_number,
                order=len(page.blocks),
                global_order=global_order,
                asset_id=context.asset_id,
            )
            for block in mapped:
                page.blocks.append(block)
                global_order += 1
        page.text = "\n".join(
            block.searchable_text() for block in page.blocks if block.searchable_text()
        )
        if not page.blocks:
            page.status = "empty"
            page.warnings.append("MinerU 未识别到可用内容")
        pages.append(page)

    document = DocumentIR(
        document_id=context.asset_id,
        asset_id=context.asset_id,
        parse_run_id=context.parse_run_id,
        doc_type=context.doc_type,
        file_sha256=context.file_sha256,
        parser_name="MinerU",
        parser_version=str(version),
        config_version=f"mineru-{tier}-v1",
        pages=pages,
        warnings=[warning for page in pages for warning in page.warnings][:50],
    )
    document.sections = build_sections(document, document_title=context.title)
    document.page_count = len(pages)
    return document


def _map_item(
    item: dict[str, Any],
    *,
    block_id: str,
    page_number: int,
    order: int,
    global_order: int,
    asset_id: str,
) -> list[BlockIR]:
    kind = str(item.get("type") or "paragraph")
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    source = SourceSpan(asset_id=asset_id, page_number=page_number)

    if kind == "title":
        text = _span_text(content.get("title_content"))
        level = _bounded_int(content.get("level"), 1, 6, 1)
        return [_block(block_id, page_number, order, global_order, "heading", text,
                       source, level=level)] if text else []

    if kind == "paragraph":
        text = _span_text(content.get("paragraph_content"))
        return [_block(block_id, page_number, order, global_order, "paragraph", text, source)] if text else []

    if kind in {"list", "index"}:
        items = content.get("list_items")
        blocks = []
        for entry in items if isinstance(items, list) else []:
            text = _span_text(entry.get("item_content")) if isinstance(entry, dict) else _span_text(entry)
            if text:
                blocks.append(_block(
                    f"{block_id}-{len(blocks) + 1}", page_number, order + len(blocks),
                    global_order + len(blocks), "list_item", text, source,
                ))
        return blocks

    if kind == "equation_interline":
        raw_latex = content.get("math_content")
        latex = raw_latex.strip() if isinstance(raw_latex, str) else ""
        return [_block(block_id, page_number, order, global_order, "equation", latex,
                       source, latex=latex)] if latex else []

    if kind == "table":
        raw_html = content.get("html")
        html = raw_html if isinstance(raw_html, str) else ""
        rows = _table_rows(html)
        if not rows:
            text = _plain_text(html)
            if not text:
                return []
            block = _block(block_id, page_number, order, global_order, "paragraph", text, source)
            block.warnings.append("表格行列未识别，已保留表格文本，请核对原文")
            return [block]
        text = "\n".join(" | ".join(row) for row in rows)
        return [_block(block_id, page_number, order, global_order, "table", text, source,
                       table=TableData(rows=rows, header_rows=1))]

    if kind in {"image", "chart"}:
        description = _span_text(content.get("content"))
        if not description:
            captions = content.get("image_caption" if kind == "image" else "chart_caption")
            description = _span_text(captions)
        subtype = str(item.get("sub_type") or "")
        figure_kind = subtype if subtype in {"diagram", "chart", "circuit", "photo", "formula", "table"} else (
            "chart" if kind == "chart" else "other"
        )
        figure = FigureData(kind=figure_kind, description=description or None, uncertain=not bool(description))
        return [_block(block_id, page_number, order, global_order, "figure", description, source,
                       figure=figure)]

    if kind in {"code", "algorithm"}:
        text = _span_text(content.get("code_content") or content.get("algorithm_content"))
        return [_block(block_id, page_number, order, global_order, "code", text, source)] if text else []

    if kind in {"page_footnote", "page_header", "page_footer", "page_number", "page_aside_text"}:
        key = next((name for name in content if name.endswith("_content")), None)
        text = _span_text(content.get(key)) if key else _span_text(content)
        return [_block(block_id, page_number, order, global_order, "paragraph", text, source)] if text else []

    return []


def _block(
    block_id: str,
    page_number: int,
    order: int,
    global_order: int,
    kind: str,
    text: str,
    source: SourceSpan,
    *,
    level: int = 0,
    latex: str | None = None,
    table: TableData | None = None,
    figure: FigureData | None = None,
) -> BlockIR:
    return BlockIR(
        block_id=block_id,
        page_number=page_number,
        order=order,
        global_order=global_order,
        type=kind,
        level=level,
        text=text,
        latex=latex,
        table=table,
        figure=figure,
        source=source,
        extraction="mineru",
    )


def _span_text(value: Any) -> str:
    return _span_content(value).strip()


def _span_content(value: Any) -> str:
    """Keep inter-span whitespace and literal LaTeX intact until block boundaries."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_span_content(item) for item in value)
    if isinstance(value, dict):
        text = value.get("content")
        if isinstance(text, (str, list)):
            return _span_content(text)
        return ""
    return ""


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return value.strip()
    return " ".join(" ".join(parser.rows).split())


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.rows.append(data.strip())


def _table_rows(value: str) -> list[list[str]]:
    if not value:
        return []

    class TableExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.rows: list[list[str]] = []
            self.row: list[str] | None = None
            self.cell: list[str] | None = None

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "tr":
                self.row = []
            elif tag in {"td", "th"} and self.row is not None:
                self.cell = []

        def handle_data(self, data: str) -> None:
            if self.cell is not None and data.strip():
                self.cell.append(data.strip())

        def handle_endtag(self, tag: str) -> None:
            if tag in {"td", "th"} and self.row is not None:
                self.row.append(" ".join(self.cell or []).strip())
                self.cell = None
            elif tag == "tr" and self.row is not None:
                if any(self.row):
                    self.rows.append(self.row)
                self.row = None

    parser = TableExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return []
    return parser.rows


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default
