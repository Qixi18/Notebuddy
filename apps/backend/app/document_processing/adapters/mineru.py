"""Optional local MinerU adapter for the NoteBuddy document IR.

MinerU owns layout analysis, OCR, tables, equations, and document-specific
normalization.  This adapter translates its public Content List V2 output into
NoteBuddy's existing IR so downstream quality checks and generation stay the
same.  MinerU remains an optional dependency and is never contacted remotely.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.metadata
import importlib.util
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.document_processing.adapters.common import is_equation
from app.document_processing.adapters.pdf import ParseContext
from app.document_processing.engines import pdf_text
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


def _ensure_windows_vlm_utf8_locale(tier: str) -> None:
    """Use UTF-8 for local llama.cpp VLM token/path conversion on Windows."""
    if os.name != "nt" or tier not in {"standard", "advanced"}:
        return
    import locale

    current = locale.setlocale(locale.LC_CTYPE)
    if "utf" in current.lower():
        return
    try:
        # MinerU's native llama.cpp binding converts some model metadata via
        # the active multibyte code page; CP936 raises on valid UTF-8 tokens.
        locale.setlocale(locale.LC_CTYPE, ".UTF-8")
    except locale.Error as exc:
        raise MinerUUnavailable(
            "Windows 本地视觉模型需要 UTF-8 区域设置；无法切换 C locale"
        ) from exc


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


def _is_blank_page_model_output(items: Any) -> bool:
    """Recognize the VLM's explicit empty-page explanation as metadata, not source text."""
    if not isinstance(items, list) or len(items) != 1:
        return False
    if not isinstance(items[0], dict) or items[0].get("type") != "paragraph":
        return False
    content = items[0].get("content")
    text = _span_text(content.get("paragraph_content")) if isinstance(content, dict) else ""
    normalized = re.sub(r"\s+", " ", text).casefold()
    return (
        "image contains no text or content to process" in normalized
        and "blank white background" in normalized
        and "empty string" in normalized
    )


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

    # Flash keeps text PDFs model-free and uses the cached small ONNX models
    # for scanned pages, avoiding heavyweight VLM downloads on CPU.
    tier = (os.getenv("NOTEBOOK_MINERU_TIER", "flash").strip().lower() or "flash")
    if tier not in {"flash", "basic", "standard", "advanced"}:
        raise ValueError("NOTEBOOK_MINERU_TIER 必须是 flash、basic、standard 或 advanced")

    _ensure_windows_vlm_utf8_locale(tier)
    parsed = mineru_parse(
        path,
        tier=tier,
        ocr_mode="auto",
        image_analysis=os.getenv("NOTEBOOK_MINERU_IMAGE_ANALYSIS", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    pages_content = render(parsed.middle_json, RenderFormat.CONTENT_LIST_V2)
    page_infos = list(getattr(parsed.middle_json, "pages", []) or [])
    if context.doc_type == "image":
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            source_pages = {1: pdf_text.RawPage(page_number=1, width=image.width,
                                                height=image.height)}
    else:
        source_document = pdf_text.extract_pdf(path)
        source_pages = {page.page_number: page for page in source_document.pages}
    version = availability()["version"]
    run_prefix = context.parse_run_id[:8]
    pages: list[PageIR] = []
    global_order = 0

    for index, items in enumerate(pages_content):
        info = page_infos[index] if index < len(page_infos) else None
        page_idx = int(getattr(info, "page_idx", index)) if info is not None else index
        page_number = page_idx + 1
        source_page = source_pages.get(page_number)
        page = PageIR(
            page_id=f"{context.parse_run_id}-p{page_number}",
            page_number=page_number,
            width=source_page.width if source_page else None,
            height=source_page.height if source_page else None,
            rotation=source_page.rotation if source_page else 0,
            extraction="mineru",
            status="parsed",
        )
        if _is_blank_page_model_output(items):
            page.status = "empty"
            page.warnings.append("MinerU 视觉模型报告空白页，已忽略其描述文本")
            items = []
        visual_indices: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            is_visual = item.get("type") in {"image", "chart", "table", "equation_interline"}
            kind = item.get("type")
            raw_block = _find_raw_block(
                parsed.middle_json, page_idx, visual_indices.get(kind, 0), item,
            ) if is_visual else None
            if is_visual:
                visual_indices[kind] = visual_indices.get(kind, 0) + 1
            mapped = _map_item(
                item,
                block_id=f"{run_prefix}-p{page_number}-b{len(page.blocks) + 1}",
                page_number=page_number,
                order=len(page.blocks),
                global_order=global_order,
                asset_id=context.asset_id,
                image_store=lambda payload, suffix: _store_image(
                    context.asset_id, context.parse_run_id, payload, suffix,
                ),
                raw_block=raw_block,
                image_fallback=lambda box, page_number=page_number: _render_figure_crop(
                    path, source_pages.get(page_number), box,
                    context.asset_id, context.parse_run_id,
                ),
            )
            for block in mapped:
                if is_visual and raw_block is None:
                    block.warnings.append("MinerU 原始视觉块未匹配，图片使用页面坐标回退")
                page.blocks.append(block)
                global_order += 1
        page.text = "\n".join(
            block.searchable_text() for block in page.blocks if block.searchable_text()
        )
        if not page.blocks:
            page.status = "needs_ocr" if context.doc_type == "image" else "empty"
            page.warnings.append("MinerU 未识别到可用内容")
        if context.doc_type == "pdf":
            # MinerU may read text inside an embedded figure as ordinary paragraphs.
            # Preserve the original PDF image when no visual block was recognized.
            source_page = source_pages.get(page_number)
            if source_page is not None:
                from app.document_processing.adapters.pdf import _image_area_ratio
                from app.notes.attachments import sniff_image_mime

                for embedded in source_page.image_blocks:
                    if embedded.xref is None or _image_area_ratio(source_page, embedded) < 0.01:
                        continue
                    if not source_page.rotation and _embedded_image_covered(
                        embedded.bbox, source_page.width, source_page.height, page.blocks,
                    ):
                        continue
                    payload = pdf_text.extract_pdf_image(path, embedded.xref)
                    mime = sniff_image_mime(payload or b"")
                    suffix = {"image/png": ".png", "image/jpeg": ".jpg",
                              "image/webp": ".webp"}.get(mime)
                    if not payload or not suffix:
                        continue
                    key = _store_image(context.asset_id, context.parse_run_id, payload, suffix)
                    page.blocks.append(BlockIR(
                        block_id=f"{run_prefix}-p{page_number}-embedded-{len(page.blocks) + 1}",
                        page_number=page_number, order=len(page.blocks), global_order=global_order,
                        type="image", text="", figure=FigureData(image_key=key, uncertain=True),
                        source=SourceSpan(asset_id=context.asset_id, page_number=page_number,
                                          bbox=embedded.bbox), bbox=embedded.bbox,
                        extraction="native_text", warnings=["保留原 PDF 内嵌图片，图中内容需核对"],
                    ))
                    global_order += 1
        if context.doc_type == "image" and page_number == 1:
            key = _store_image(context.asset_id, context.parse_run_id, path.read_bytes(),
                               path.suffix.lower())
            page.blocks.append(BlockIR(
                block_id=f"{run_prefix}-p{page_number}-original", page_number=page_number,
                order=len(page.blocks), global_order=global_order, type="image", text="",
                figure=FigureData(image_key=key, uncertain=True),
                source=SourceSpan(asset_id=context.asset_id, page_number=page_number),
                extraction="mineru", warnings=["原始图片保留为来源证据，图中内容需核对"],
            ))
            global_order += 1
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


def _embedded_image_covered(
    bbox: list[float] | None, width: float | None, height: float | None, blocks: list[BlockIR],
) -> bool:
    """Only suppress an embedded image when a MinerU visual covers most of it."""
    if not bbox or not width or not height:
        return False
    x0, y0, x1, y1 = bbox
    area = max(0, x1 - x0) * max(0, y1 - y0)
    if not area:
        return False
    for block in blocks:
        if not block.figure or not block.figure.image_key or not block.bbox:
            continue
        a, b, c, d = block.bbox
        a, c = a * width / 1000, c * width / 1000
        b, d = b * height / 1000, d * height / 1000
        intersection = max(0, min(x1, c) - max(x0, a)) * max(0, min(y1, d) - max(y0, b))
        if intersection / area >= 0.9:
            return True
    return False


def _map_item(
    item: dict[str, Any],
    *,
    block_id: str,
    page_number: int,
    order: int,
    global_order: int,
    asset_id: str,
    image_store: Any = None,
    raw_block: dict[str, Any] | None = None,
    image_fallback: Any = None,
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
        if text and is_equation(text):
            block = _block(block_id, page_number, order, global_order, "equation", text,
                            source, latex=text)
            block.warnings.append("从独立数学表达式段落提取；请核对公式语义及上下标")
            return [block]
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
        bbox = item.get("bbox")
        normalized_bbox = None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                normalized_bbox = [float(value) for value in bbox]
            except (TypeError, ValueError):
                normalized_bbox = None
        figure = FigureData(kind=figure_kind, description=description or None, uncertain=not bool(description))
        image_key = _materialize_block_image(raw_block, image_store)
        if image_key is None and callable(image_fallback):
            image_key = image_fallback(normalized_bbox)
        figure.image_key = image_key
        vision_blocks = _enrich_mineru_figure(
            figure, image_key, asset_id=asset_id, page_number=page_number,
            order=order + 1, global_order=global_order + 1, bbox=normalized_bbox,
        ) if image_key else []
        if image_key:
            figure.image_key = image_key
        source.bbox = normalized_bbox
        source.location_label = "MinerU 原始图像块"
        block = _block(block_id, page_number, order, global_order, "figure", description, source,
                       figure=figure, bbox=normalized_bbox)
        return [block, *vision_blocks]

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
    bbox: list[float] | None = None,
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
        bbox=bbox,
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


def _store_image(asset_id: str, run_id: str, payload: bytes, suffix: str) -> str:
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("unsupported MinerU image format")
    digest = hashlib.sha256(payload).hexdigest()[:20]
    key = f"derived/figures/{asset_id}/{run_id}/{digest}{suffix}"
    root = settings.data_dir.resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("invalid derived image path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
    return key


def _render_figure_crop(
    path: Path, source_page: Any, bbox: list[float] | None, asset_id: str, run_id: str,
) -> str | None:
    if source_page is None or not bbox or len(bbox) != 4:
        return None
    # MinerU 4 Content List V2 always supplies coordinates normalized to 0..1000.
    if any(value < 0 or value > 1000 for value in bbox):
        return None
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        from io import BytesIO

        from PIL import Image, ImageOps

        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source)
                box = (int(bbox[0] * image.width / 1000), int(bbox[1] * image.height / 1000),
                       int(bbox[2] * image.width / 1000), int(bbox[3] * image.height / 1000))
                if box[2] <= box[0] or box[3] <= box[1]:
                    return None
                output = BytesIO()
                image.crop(box).save(output, format="PNG")
                return _store_image(asset_id, run_id, output.getvalue(), ".png")
        except (OSError, ValueError):
            return None
    module = pdf_text._pymupdf()
    if module is None:
        rendered = pdf_text.render_pdf_page(path, source_page.page_number, dpi=180)
        if not rendered or not source_page.width or not source_page.height:
            return None
        try:
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(rendered)) as image:
                x0, y0, x1, y1 = bbox
                x0, x1 = x0 * image.width / 1000, x1 * image.width / 1000
                y0, y1 = y0 * image.height / 1000, y1 * image.height / 1000
                box = (max(0, int(x0)), max(0, int(y0)), min(image.width, int(x1)), min(image.height, int(y1)))
                if box[2] <= box[0] or box[3] <= box[1]:
                    return None
                output = BytesIO()
                image.crop(box).save(output, format="PNG")
                return _store_image(asset_id, run_id, output.getvalue(), ".png")
        except Exception:
            return None
    try:
        with module.open(str(path)) as document:
            if source_page.page_number > len(document):
                return None
            page = document[source_page.page_number - 1]
            width, height = float(page.rect.width), float(page.rect.height)
            box = [bbox[0] * width / 1000, bbox[1] * height / 1000,
                   bbox[2] * width / 1000, bbox[3] * height / 1000]
            rect = module.Rect(*box) & page.rect
            if rect.is_empty or rect.width < 2 or rect.height < 2:
                return None
            pixmap = page.get_pixmap(matrix=module.Matrix(2, 2), clip=rect, alpha=False)
            return _store_image(asset_id, run_id, pixmap.tobytes("png"), ".png")
    except Exception:
        return None


def _enrich_mineru_figure(
    figure: FigureData, image_key: str, *, asset_id: str, page_number: int,
    order: int, global_order: int, bbox: list[float] | None,
) -> list[BlockIR]:
    """Best-effort model enrichment of a preserved local image crop."""
    base_url = (os.getenv("NOTEBOOK_VISION_BASE_URL") or "").strip()
    model = (os.getenv("NOTEBOOK_VISION_MODEL") or "").strip()
    if not base_url or not model:
        return []
    root = settings.data_dir.resolve()
    image_path = (root / image_key).resolve()
    if not image_path.is_relative_to(root) or not image_path.is_file():
        return []
    try:
        from app.document_processing.engines.vision import describe

        result = describe(image_path.read_bytes(), mime={
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(image_path.suffix.lower(), "image/png"))
    except Exception:
        return []
    if getattr(result, "warnings", None) or not (
        getattr(result, "description", None) or getattr(result, "latex", None)
        or getattr(result, "table", None) or getattr(result, "figure", None)
    ):
        return []
    blocks: list[BlockIR] = []
    table = getattr(result, "table", None)
    if table and isinstance(table.get("rows"), list):
        rows = [[str(cell) for cell in row] for row in table["rows"] if isinstance(row, list)]
        if rows:
            blocks.append(_block(
                f"vision-{image_key.rsplit('/', 1)[-1].split('.', 1)[0][:16]}-table",
                page_number, order, global_order, "table",
                "\n".join(" | ".join(row) for row in rows),
                SourceSpan(asset_id=asset_id, page_number=page_number, bbox=bbox),
                table=TableData(rows=rows, header_rows=int(table.get("header_rows", 1))),
            ))
    latex = getattr(result, "latex", None)
    if latex:
        blocks.append(_block(
            f"vision-{image_key.rsplit('/', 1)[-1].split('.', 1)[0][:16]}-equation",
            page_number, order, global_order,
            "equation", latex,
            SourceSpan(asset_id=asset_id, page_number=page_number, bbox=bbox), latex=latex,
        ))
    description = getattr(result, "description", None)
    result_figure = getattr(result, "figure", None)
    if description or result_figure:
        details = result_figure or {}
        kind = details.get("kind") if details.get("kind") in {
            "diagram", "chart", "circuit", "photo", "formula", "table", "other",
        } else figure.kind
        enriched = FigureData(
            kind=kind, description=description,
            nodes=[str(value)[:300] for value in details.get("nodes") or []][:200],
            edges=[str(value)[:300] for value in details.get("edges") or []][:400],
        uncertain=bool(getattr(result, "uncertain", True)), image_key=image_key,
        )
        blocks.append(_block(
            f"vision-{image_key.rsplit('/', 1)[-1].split('.', 1)[0][:16]}-figure",
            page_number, order, global_order, "figure",
            description or "；".join(enriched.nodes),
            SourceSpan(asset_id=asset_id, page_number=page_number, bbox=bbox), figure=enriched,
        ))
    for offset, block in enumerate(blocks):
        block.order = order + offset
        block.global_order = global_order + offset
        block.block_id = f"vision-{asset_id[:8]}-p{page_number}-{image_key.rsplit('/', 1)[-1][:12]}-{offset}"
        if getattr(result, "uncertain", True):
            block.confidence = None
            block.warnings.append("视觉识别结果不确定，请核对原图")
        else:
            block.confidence = 0.8
        if block.source:
            block.source.location_label = "视觉模型补充识别"
    return blocks


def _find_raw_block(
    materialized: Any, page_idx: int, index: int, rendered_item: dict[str, Any],
) -> Any | None:
    """Find a typed MinerU image payload matching the rendered content item."""
    pages = getattr(materialized, "pages", None)
    if not isinstance(pages, list) or page_idx < 0:
        return None
    page = next((item for item in pages if getattr(item, "page_idx", None) == page_idx), None)
    blocks = getattr(page, "blocks", None) if page is not None else None
    if not isinstance(blocks, list):
        return None
    target_type = rendered_item.get("type")
    raw_type = "equation" if target_type == "equation_interline" else target_type
    candidates = [block for block in blocks if
                  getattr(getattr(block, "type", None), "value", getattr(block, "type", None))
                  == raw_type]
    if index < 0 or index >= len(candidates):
        return None
    parent = candidates[index]
    children = getattr(parent, "content", None)
    if isinstance(children, list):
        expected = f"{raw_type}_body"
        return next((child for child in children if
                     getattr(getattr(child, "type", None), "value", getattr(child, "type", None))
                     == expected), None)
    return parent


def _mineru_image_bytes(block: Any) -> tuple[bytes, str] | None:
    if block is None:
        return None
    encoded = getattr(block, "image_base64", None)
    if isinstance(encoded, str) and encoded:
        match = re.fullmatch(r"data:image/(png|jpeg|jpg|webp);base64,(.*)", encoded, re.DOTALL)
        if match:
            try:
                suffix = ".jpg" if match.group(1) in {"jpeg", "jpg"} else f".{match.group(1)}"
                return base64.b64decode(match.group(2), validate=True), suffix
            except (ValueError, binascii.Error):
                return None
    path = getattr(block, "image_path", None)
    if isinstance(path, str) and Path(path).is_file():
        suffix = Path(path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            return Path(path).read_bytes(), suffix
    return None


def _materialize_block_image(block: Any, image_store: Any) -> str | None:
    image = _mineru_image_bytes(block)
    if not image or not callable(image_store):
        return None
    payload, suffix = image
    return image_store(payload, suffix)
