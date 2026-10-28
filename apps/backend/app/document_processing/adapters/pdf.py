"""PDF -> Document IR adapter.

Per page, the adapter chooses the cheapest strategy that can be trusted:

1. Native text layer (PyMuPDF layout or pypdf text) -> headings/paragraphs/lists,
   tables when a table finder is available, figures for embedded images.
2. No text layer -> OCR when an engine is available; otherwise the page is
   marked ``needs_ocr`` and contributes to a blocking quality issue.
3. Equations are detected but only carry LaTeX when a vision engine supplies it;
   otherwise they are marked uncertain instead of inventing formulas.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.document_processing.adapters.common import (
    TextBlockDraft,
    block_body_size,
    heading_level,
    is_equation,
    make_block,
    text_drafts,
)
from app.document_processing.engines import ocr as ocr_engine
from app.document_processing.engines import pdf_text
from app.document_processing.engines import vision as vision_engine
from app.document_processing.engines.pdf_text import RawPage, RawTable
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    QualityReport,
    SourceSpan,
    TableData,
)
from app.document_processing.normalization.sections import build_sections

logger = logging.getLogger(__name__)

SCAN_IMAGE_AREA_RATIO = 0.6
TABLE_OVERLAP_RATIO = 0.55
MIN_PAGE_TEXT_CHARS = 8


@dataclass
class ParseContext:
    asset_id: str
    parse_run_id: str
    doc_type: str = "pdf"
    file_sha256: str | None = None
    title: str = ""
    max_vision_images: int = 12
    ocr_language: str = "chi_sim+eng"


def parse_pdf(
    path: Path,
    context: ParseContext,
    *,
    render_store: Callable[[int, bytes], str] | None = None,
    ocr_available: bool | None = None,
    vision_available: bool | None = None,
    ocr_recognize: Callable[..., object] | None = None,
    vision_describe: Callable[..., object] | None = None,
    figure_store: Callable[[int, bytes, str], str] | None = None,
) -> DocumentIR:
    ocr_available = ocr_engine.availability().available if ocr_available is None else ocr_available
    vision_available = vision_engine.availability().available if vision_available is None else vision_available
    recognize = ocr_recognize or ocr_engine.recognize
    describe = vision_describe or vision_engine.describe

    def should_render(page: RawPage) -> bool:
        return bool(render_store) and (ocr_available or vision_available) and not page.has_text_layer

    raw = pdf_text.extract_pdf(path, render_when=should_render if render_store else None)
    body_size = block_body_size([block for page in raw.pages for block in page.text_blocks])

    pages: list[PageIR] = []
    global_order = 0
    vision_budget = max(0, context.max_vision_images)
    run_prefix = context.parse_run_id[:8]
    for raw_page in raw.pages:
        render_key: str | None = None
        if raw_page.render_png and render_store is not None:
            try:
                render_key = render_store(raw_page.page_number, raw_page.render_png)
            except Exception:  # pragma: no cover - storage failure must not lose text
                logger.warning("Could not store page rendering", exc_info=True)

        page = PageIR(
            page_id=f"{context.parse_run_id}-p{raw_page.page_number}",
            page_number=raw_page.page_number,
            width=raw_page.width,
            height=raw_page.height,
            rotation=raw_page.rotation,
            render_key=render_key,
            extraction="native_text" if raw_page.has_text_layer else "none",
            status="parsed",
            text=raw_page.text,
            confidence=1.0 if raw_page.has_text_layer else None,
        )
        scanned = not raw_page.has_text_layer and (
            raw_page.render_png is not None or raw_page.render_error is not None
            or _largest_image_area_ratio(raw_page) >= SCAN_IMAGE_AREA_RATIO
        )

        drafts: list[TextBlockDraft] = []
        for raw_block in raw_page.text_blocks:
            drafts.extend(text_drafts(raw_block, body_size=body_size))

        vision_blocks: list[BlockIR] = []
        if scanned:
            png = raw_page.render_png
            if png is None and render_store is not None and (ocr_available or vision_available):
                png = _render_single(path, raw_page.page_number)
                if png:
                    try:
                        render_key = render_store(raw_page.page_number, png)
                        page.render_key = render_key
                    except Exception:  # pragma: no cover
                        render_key = None
            blank_page = bool(png and not raw_page.image_blocks and _is_white_page(png))
            if raw_page.render_error:
                page.status = "failed"
                page.warnings.append(raw_page.render_error)
            elif blank_page:
                page.status = "empty"
                page.warnings.append("本页渲染为空白页")
            elif png is None and ocr_available:
                page.status = "needs_ocr"
                page.warnings.append("扫描页无法渲染，OCR 未执行")
            elif ocr_available and png:
                try:
                    result = recognize(png, language=context.ocr_language)
                    ocr_drafts, confidence, warnings = _ocr_drafts(result)
                    drafts = ocr_drafts
                    page.extraction = "ocr"
                    page.confidence = confidence
                    page.status = (
                        "needs_ocr" if not ocr_drafts else
                        "partial" if warnings or page.rotation else "parsed"
                    )
                    page.warnings.extend(warnings)
                    if not ocr_drafts:
                        page.warnings.append("OCR 未识别到可用文字；本页未被视为解析成功")
                    page.text = "\n".join(draft.text for draft in drafts)
                except Exception as exc:
                    page.status = "needs_ocr"
                    page.warnings.append(f"OCR 失败：{type(exc).__name__}: {exc}")
            elif vision_available and png:
                page.status = "partial"
                page.warnings.append("本页没有文字层，改由视觉引擎识别")
            elif not ocr_available:
                page.status = "needs_ocr"
                page.warnings.append("本页没有文字层，需要 OCR；当前环境没有可用 OCR 引擎")

            if not drafts and vision_available and png and not raw_page.render_error and not blank_page:
                vision_blocks = _describe_page_image(
                    png, page, context, render_key=render_key,
                    start_global=global_order, describe=describe,
                )
                if vision_blocks:
                    page.status = "partial"
                    page.extraction = "vision"
                    page.warnings.append("扫描页由视觉引擎补充识别，结果需人工核对")
                    page.text = "\n".join(block.text for block in vision_blocks if block.text)

        table_boxes = [table.bbox for table in raw_page.tables if table.bbox]
        drafts = _drop_blocks_inside_tables(drafts, table_boxes)

        blocks: list[BlockIR] = []
        for draft in drafts:
            block_id = f"{run_prefix}-p{raw_page.page_number}-b{len(blocks) + 1}"
            blocks.append(make_block(
                draft, block_id=block_id, page_number=raw_page.page_number,
                order=len(blocks), global_order=global_order,
                asset_id=context.asset_id, extraction=page.extraction,
                confidence=page.confidence, render_key=render_key,
            ))
            global_order += 1

        if vision_blocks:
            blocks.extend(vision_blocks)
            global_order += len(vision_blocks)

        for table in raw_page.tables:
            table_block = _table_block(
                table, block_id=f"{run_prefix}-p{raw_page.page_number}-t{len(blocks) + 1}",
                page_number=raw_page.page_number, order=len(blocks), global_order=global_order,
                asset_id=context.asset_id, render_key=render_key,
            )
            if table_block is not None:
                blocks.append(table_block)
                global_order += 1

        if scanned and png and figure_store and page.status not in {"empty", "failed"}:
            # Keep the rendered scan as independently addressable visual evidence,
            # including when OCR produced text but missed a diagram or table.
            key = figure_store(raw_page.page_number, png, ".png")
            blocks.append(BlockIR(
                block_id=f"{run_prefix}-p{raw_page.page_number}-scan", page_number=raw_page.page_number,
                order=len(blocks), global_order=global_order, type="image", text="",
                figure=FigureData(image_key=key, uncertain=True), extraction="none",
                source=SourceSpan(asset_id=context.asset_id, page_number=raw_page.page_number,
                                  render_key=render_key),
                warnings=["扫描页面作为图像证据保留，图表与公式需核对"],
            ))
            global_order += 1

        if not scanned:
            for image in raw_page.image_blocks:
                if image.bbox is None:
                    continue
                if _image_area_ratio(raw_page, image) < 0.01:
                    # Decorative rules/logos are not teaching figures.
                    continue
                figure = _build_figure(
                    path, raw_page, image, context,
                    vision_available=vision_available, describe=describe,
                    vision_budget=vision_budget, figure_store=figure_store,
                )
                if figure is not None:
                    vision_budget = figure[1]
                    blocks.append(_figure_block(
                        figure, block_id=f"{run_prefix}-p{raw_page.page_number}-f{len(blocks) + 1}",
                        page_number=raw_page.page_number, order=len(blocks),
                        global_order=global_order, asset_id=context.asset_id,
                        bbox=image.bbox, render_key=render_key,
                    ))
                    global_order += 1

        if not blocks and not scanned:
            page.status = "empty"
            page.warnings.append("本页没有可用的文字或结构化内容")
        elif blocks and page.status == "parsed" and not page.text.strip() and not any(
            block.table or block.figure for block in blocks
        ):
            page.status = "empty"

        page.blocks = blocks
        pages.append(page)

    document = DocumentIR(
        document_id=context.asset_id,
        asset_id=context.asset_id,
        parse_run_id=context.parse_run_id,
        doc_type="pdf",
        file_sha256=context.file_sha256,
        parser_name=raw.engine.name,
        parser_version=raw.engine.version,
        config_version="pdf-layout-v1",
        pages=pages,
        warnings=[instruction for page in pages for instruction in page.warnings][:50],
    )
    document.sections = build_sections(document, document_title=context.title)
    document.page_count = len(pages)
    document.quality = QualityReport()  # replaced by service.assess
    return document


def _is_white_page(png: bytes) -> bool:
    """Only call a page blank if every rendered RGB pixel is exactly white."""
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(BytesIO(png)) as image:
            return all(lo == 255 and hi == 255 for lo, hi in image.convert("RGB").getextrema())
    except (OSError, ValueError):
        return False


def _largest_image_area_ratio(page: RawPage) -> float:
    if not page.width or not page.height:
        return 0.0
    page_area = float(page.width) * float(page.height)
    if page_area <= 0:
        return 0.0
    best = 0.0
    for image in page.image_blocks:
        if not image.bbox:
            continue
        best = max(best, _image_area_ratio(page, image))
    return best


def _image_area_ratio(page: RawPage, image: pdf_text.RawImageBlock) -> float:
    if not page.width or not page.height or not image.bbox:
        return 0.0
    page_area = float(page.width) * float(page.height)
    box = image.bbox
    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    return area / page_area if page_area > 0 else 0.0


def _render_single(path: Path, page_number: int) -> bytes | None:
    raw = pdf_text.extract_pdf(path, render_when=lambda page: page.page_number == page_number)
    for page in raw.pages:
        if page.page_number == page_number:
            return page.render_png
    return None


def _intersection_ratio(inner: list[float], outer: list[float]) -> float:
    x0 = max(inner[0], outer[0])
    y0 = max(inner[1], outer[1])
    x1 = min(inner[2], outer[2])
    y1 = min(inner[3], outer[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inner_area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    if inner_area <= 0:
        return 0.0
    return ((x1 - x0) * (y1 - y0)) / inner_area


def _drop_blocks_inside_tables(
    drafts: list[TextBlockDraft], table_boxes: list[list[float]],
) -> list[TextBlockDraft]:
    if not table_boxes:
        return drafts
    kept: list[TextBlockDraft] = []
    for draft in drafts:
        if draft.bbox and any(_intersection_ratio(draft.bbox, box) >= TABLE_OVERLAP_RATIO
                              for box in table_boxes):
            continue
        kept.append(draft)
    return kept


def _table_block(
    table: RawTable, *, block_id: str, page_number: int, order: int, global_order: int,
    asset_id: str, render_key: str | None,
) -> BlockIR | None:
    rows = [[cell.strip() for cell in row] for row in table.rows if row]
    if not rows or not any(any(cell for cell in row) for row in rows):
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    from app.document_processing.ir import SourceSpan

    return BlockIR(
        block_id=block_id, page_number=page_number, order=order, global_order=global_order,
        type="table", text="\n".join(" | ".join(row) for row in rows),
        table=TableData(rows=rows, header_rows=1), bbox=table.bbox,
        source=SourceSpan(asset_id=asset_id, page_number=page_number, bbox=table.bbox,
                          render_key=render_key),
        extraction="native_text", confidence=0.8,
    )


def _build_figure(
    path: Path,
    page: RawPage,
    image: pdf_text.RawImageBlock,
    context: ParseContext,
    *,
    vision_available: bool,
    describe: Callable[..., object],
    vision_budget: int,
    figure_store: Callable[[int, bytes, str], str] | None = None,
) -> tuple[FigureData, int, list[str]] | None:
    if image.bbox is None:
        return None
    description = None
    kind = "other"
    latex = None
    nodes: list[str] = []
    edges: list[str] = []
    uncertain = True
    warnings: list[str] = []
    image_key = None
    suffix = ".png"
    if image.xref is not None:
        data = pdf_text.extract_pdf_image(path, image.xref)
        if data:
            if figure_store:
                module = pdf_text._pymupdf()
                if module is not None:
                    try:
                        with module.open(str(path)) as document:
                            extracted = document.extract_image(image.xref)
                            suffix = "." + str(extracted.get("ext") or "png")
                    except Exception:
                        logger.debug("Could not determine embedded image format", exc_info=True)
                try:
                    image_key = figure_store(page.page_number, data, suffix)
                except Exception:
                    logger.warning("Could not store extracted figure image", exc_info=True)
            if vision_available and vision_budget > 0:
                vision_budget -= 1
                try:
                    result = describe(data, mime={
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                    }.get(suffix, "image/png"))
                    description = getattr(result, "description", None)
                    latex = getattr(result, "latex", None)
                    figure = getattr(result, "figure", None) or {}
                    if isinstance(figure, dict):
                        kind = str(figure.get("kind") or "other")
                        nodes = [str(item) for item in figure.get("nodes") or []][:40]
                        edges = [str(item) for item in figure.get("edges") or []][:60]
                    uncertain = bool(getattr(result, "uncertain", True))
                    warnings = list(getattr(result, "warnings", []) or [])
                except Exception as exc:  # pragma: no cover - optional enrichment
                    warnings.append(f"视觉识别失败：{type(exc).__name__}")
    if description is None and latex is None:
        warnings.append("图像内容未解释（视觉引擎不可用或未启用）")
    return (
        FigureData(kind=kind if kind else "other", description=description, latex=latex,
                   nodes=nodes, edges=edges, uncertain=uncertain, image_key=image_key),
        vision_budget,
        warnings,
    )


def _figure_block(
    figure: tuple[FigureData, int, list[str]],
    *, block_id: str, page_number: int, order: int, global_order: int,
    asset_id: str, bbox: list[float] | None, render_key: str | None,
) -> BlockIR:
    from app.document_processing.ir import SourceSpan

    data, _budget, warnings = figure
    if data.description:
        text = data.description
    elif data.latex:
        text = data.latex
    elif data.nodes:
        text = "；".join(data.nodes)
    else:
        text = "图像内容未解析"
    return BlockIR(
        block_id=block_id, page_number=page_number, order=order, global_order=global_order,
        type="figure", text=text, latex=data.latex, figure=data, bbox=bbox,
        source=SourceSpan(asset_id=asset_id, page_number=page_number, bbox=bbox,
                          render_key=render_key),
        extraction="vision" if data.description or data.latex else "none",
        confidence=None if data.uncertain else 0.8,
        warnings=warnings,
    )


def _describe_page_image(
    png: bytes,
    page: PageIR,
    context: ParseContext,
    *,
    render_key: str | None,
    start_global: int,
    describe: Callable[..., object],
) -> list[BlockIR]:
    try:
        result = describe(png)
    except Exception:  # pragma: no cover - optional enrichment
        return []
    table = getattr(result, "table", None)
    latex = getattr(result, "latex", None)
    description = getattr(result, "description", None)
    figure = getattr(result, "figure", None) or {}
    uncertain = bool(getattr(result, "uncertain", True))
    warnings = list(getattr(result, "warnings", []) or [])
    blocks: list[BlockIR] = []
    page_number = page.page_number

    def add(block: BlockIR) -> None:
        block.block_id = f"{context.parse_run_id[:8]}-p{page_number}-v{len(blocks) + 1}"
        block.order = len(blocks)
        block.global_order = start_global + len(blocks)
        blocks.append(block)

    if isinstance(table, dict) and isinstance(table.get("rows"), list):
        rows = [[str(cell) for cell in row] for row in table["rows"] if isinstance(row, list)]
        if rows and any(any(cell.strip() for cell in row) for row in rows):
            header = table.get("header_rows") if isinstance(table.get("header_rows"), int) else 1
            add(BlockIR(
                block_id="", page_number=page_number, order=0, global_order=0, type="table",
                text="\n".join(" | ".join(row) for row in rows),
                table=TableData(rows=rows, header_rows=max(1, header)),
                source=SourceSpan(asset_id=context.asset_id, page_number=page_number,
                                  render_key=render_key),
                extraction="vision", confidence=None if uncertain else 0.75, warnings=warnings,
            ))
    if latex:
        add(BlockIR(
            block_id="", page_number=page_number, order=0, global_order=0, type="equation",
            text=str(latex), latex=str(latex),
            source=SourceSpan(asset_id=context.asset_id, page_number=page_number,
                              render_key=render_key),
            extraction="vision", confidence=None if uncertain else 0.8,
            warnings=warnings + (["公式识别结果不确定"] if uncertain else []),
        ))
    nodes = [str(item) for item in figure.get("nodes") or []][:60] if isinstance(figure, dict) else []
    edges = [str(item) for item in figure.get("edges") or []][:80] if isinstance(figure, dict) else []
    if description or nodes or edges:
        kind = str(figure.get("kind") or "other") if isinstance(figure, dict) else "other"
        add(BlockIR(
            block_id="", page_number=page_number, order=0, global_order=0, type="figure",
            text=description or "；".join(nodes) or "图像结构",
            figure=FigureData(kind=kind, description=description, nodes=nodes, edges=edges,
                              uncertain=uncertain),
            source=SourceSpan(asset_id=context.asset_id, page_number=page_number,
                              render_key=render_key),
            extraction="vision", confidence=None if uncertain else 0.8,
            warnings=warnings + (["图形识别结果不确定"] if uncertain else []),
        ))
    return blocks


def _ocr_drafts(result: object) -> tuple[list[TextBlockDraft], float | None, list[str]]:
    lines = list(getattr(result, "lines", []) or [])
    warnings = list(getattr(result, "warnings", []) or [])
    if not lines:
        return [], None, warnings + ["OCR 未识别到文字"]
    heights = [
        line.bbox[3] - line.bbox[1]
        for line in lines if getattr(line, "bbox", None) and len(line.bbox) == 4
    ]
    median_height = sorted(heights)[len(heights) // 2] if heights else 0.0
    ordered = sorted(
        lines,
        key=lambda line: (
            (line.bbox[1] if getattr(line, "bbox", None) else 0),
            (line.bbox[0] if getattr(line, "bbox", None) else 0),
        ),
    )
    groups: list[list[object]] = []
    for line in ordered:
        if not getattr(line, "text", "").strip():
            continue
        if groups and _same_ocr_block(groups[-1][-1], line, median_height):
            groups[-1].append(line)
        else:
            groups.append([line])
    drafts: list[TextBlockDraft] = []
    for group in groups:
        text = _join_ocr_text([line.text for line in group])
        bbox = _union_bbox([line.bbox for line in group if getattr(line, "bbox", None)])
        size = None
        bold = False
        level = heading_level(text, size=size, bold=bold, body_size=None)
        if level and not is_equation(text):
            drafts.append(TextBlockDraft(text=text, size=size, bold=bold, bbox=bbox,
                                         kind="heading", level=level))
        elif is_equation(text):
            drafts.append(TextBlockDraft(text=text, size=size, bold=bold, bbox=bbox,
                                         kind="equation",
                                         warnings=("OCR 识别到公式但无法还原 LaTeX，需人工核对",)))
        else:
            drafts.append(TextBlockDraft(text=text, size=size, bold=bold, bbox=bbox))
    confidences = [
        float(line.confidence) for line in lines
        if getattr(line, "confidence", None) is not None
    ]
    confidence = sum(confidences) / len(confidences) if confidences else None
    if confidence is not None and confidence < 0.6:
        warnings.append(f"OCR 平均置信度偏低（{confidence:.2f}），请核对原文")
    return drafts, confidence, warnings


def _same_ocr_block(previous: object, current: object, median_height: float) -> bool:
    prev_box = getattr(previous, "bbox", None)
    curr_box = getattr(current, "bbox", None)
    if not prev_box or not curr_box:
        return False
    if median_height and (curr_box[1] - prev_box[3]) > median_height * 1.6:
        return False
    left_delta = abs(curr_box[0] - prev_box[0])
    return left_delta <= max(median_height * 2.5, 24)


def _join_ocr_text(parts: list[str]) -> str:
    from app.document_processing.adapters.common import CJK

    result = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if result and not CJK.match(result[-1]) and not CJK.match(part[0]):
            result += " "
        result += part
    return result


def _union_bbox(boxes: list[list[float]]) -> list[float] | None:
    valid = [box for box in boxes if isinstance(box, list) and len(box) == 4]
    if not valid:
        return None
    return [
        min(box[0] for box in valid), min(box[1] for box in valid),
        max(box[2] for box in valid), max(box[3] for box in valid),
    ]
