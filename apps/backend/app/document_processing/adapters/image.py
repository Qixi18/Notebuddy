"""Image -> Document IR adapter.

The original image is always the authoritative visual evidence.  OCR provides
text when available; a vision engine may add formulas/tables/figure structure.
When neither engine is available the page is marked ``needs_ocr`` and the
document is explicitly blocked from automatic generation.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable
from pathlib import Path

from app.core.config import settings
from app.document_processing.adapters.common import (
    TextBlockDraft,
    heading_level,
    is_equation,
    make_block,
)
from app.document_processing.engines import ocr as ocr_engine
from app.document_processing.engines import vision as vision_engine
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    SourceSpan,
    TableData,
)
from app.document_processing.normalization.sections import build_sections

logger = logging.getLogger(__name__)


def _store_image_evidence(context: object, data: bytes, mime: str) -> str | None:
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime)
    if extension is None:
        return None
    digest = hashlib.sha256(data).hexdigest()[:20]
    root = settings.data_dir.resolve()
    key = f"derived/figures/{context.asset_id}/{context.parse_run_id}/original-{digest}{extension}"
    target = (root / key).resolve()
    if not target.is_relative_to(root) or target == root:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    return key


def parse_image(
    path: Path,
    context: object,
    *,
    ocr_available: bool | None = None,
    vision_available: bool | None = None,
    ocr_recognize: Callable[..., object] | None = None,
    vision_describe: Callable[..., object] | None = None,
) -> DocumentIR:
    from app.document_processing.adapters.pdf import ParseContext

    if not isinstance(context, ParseContext):
        raise TypeError("context must be ParseContext")
    ocr_available = ocr_engine.availability().available if ocr_available is None else ocr_available
    vision_available = vision_engine.availability().available if vision_available is None else vision_available
    recognize = ocr_recognize or ocr_engine.recognize
    describe = vision_describe or vision_engine.describe

    data = path.read_bytes()
    width = height = None
    rotation = 0
    ocr_bytes = data
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")
    source_mime = mime
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.width, image.height
            source_mime = {
                "PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp",
            }.get(str(image.format or "").upper(), source_mime)
            try:
                rotation = int((image.getexif() or {}).get(274, 1) or 1)
            except Exception:
                rotation = 0
            if rotation not in (0, 1):
                with ImageOps.exif_transpose(image) as upright:
                    buffer = io.BytesIO()
                    upright.save(buffer, format="PNG")
                    ocr_bytes = buffer.getvalue()
                    mime = "image/png"
                    width, height = upright.width, upright.height
    except Exception:  # pragma: no cover - malformed image is a parse failure
        logger.warning("Could not read image dimensions", exc_info=True)

    image_key = _store_image_evidence(context, data, source_mime)

    page = PageIR(
        page_id=f"{context.parse_run_id}-p1",
        page_number=1,
        width=float(width) if width else None,
        height=float(height) if height else None,
        rotation=0 if rotation in (0, 1) else 90,
        extraction="none",
        status="parsed",
        text="",
        confidence=None,
    )
    blocks: list[BlockIR] = []
    run_prefix = context.parse_run_id[:8]

    if ocr_available:
        try:
            result = recognize(ocr_bytes, language=context.ocr_language)
            drafts = _image_ocr_drafts(result)
            for index, draft in enumerate(drafts, start=1):
                blocks.append(make_block(
                    draft, block_id=f"{run_prefix}-p1-b{index}", page_number=1, order=index - 1,
                    global_order=index - 1, asset_id=context.asset_id,
                    extraction="ocr", confidence=getattr(result, "mean_confidence", None),
                ))
            page.extraction = "ocr"
            page.confidence = getattr(result, "mean_confidence", None)
            page.text = "\n".join(draft.text for draft in drafts)
            page.warnings.extend(getattr(result, "warnings", []) or [])
            if not drafts:
                page.status = "needs_ocr"
                page.warnings.append("OCR 未识别到文字")
        except Exception as exc:
            page.status = "needs_ocr"
            page.warnings.append(f"OCR 失败：{type(exc).__name__}: {exc}")
    else:
        page.status = "needs_ocr"
        page.warnings.append("图片需要 OCR/视觉识别；当前环境没有可用 OCR 引擎")

    vision_applied = False
    if vision_available:
        try:
            result = describe(ocr_bytes, mime=mime)
            vision_applied = _apply_vision(
                result, page, blocks, context, index_base=len(blocks), image_key=image_key,
            )
            if vision_applied:
                page.extraction = "vision" if page.extraction == "none" else "mixed"
                if page.status == "needs_ocr":
                    # Vision produced structure but OCR text is still missing;
                    # usable only with an explicit review warning.
                    page.status = "partial"
        except Exception as exc:  # pragma: no cover - optional enrichment
            page.warnings.append(f"视觉识别失败：{type(exc).__name__}")

    if not blocks:
        # Preserve the image itself as evidence even when no text was recognized.
        figure = FigureData(kind="other", description=None, uncertain=True)
        figure.image_key = image_key
        blocks.append(BlockIR(
            block_id=f"{run_prefix}-p1-img1", page_number=1, order=0, global_order=0, type="image",
            text="原始图片（未识别文字）", figure=figure,
            bbox=None,
            source=SourceSpan(asset_id=context.asset_id, page_number=1),
            extraction="none", confidence=None,
            warnings=list(page.warnings),
        ))
        if page.status == "parsed":
            page.status = "needs_ocr"
    elif not any(block.figure and block.figure.image_key == image_key for block in blocks):
        # OCR text and its original image are separate pieces of evidence.
        blocks.append(BlockIR(
            block_id=f"{run_prefix}-p1-img1", page_number=1, order=len(blocks),
            global_order=len(blocks), type="image", text="",
            figure=FigureData(image_key=image_key, uncertain=True),
            source=SourceSpan(asset_id=context.asset_id, page_number=1),
            extraction="none", confidence=None,
            warnings=["原始图片保留为来源证据，图中内容需核对"],
        ))

    for order, block in enumerate(blocks):
        block.order = order
        block.global_order = order
    page.blocks = blocks
    page.text = page.text or "\n".join(block.text for block in blocks if block.text)

    document = DocumentIR(
        document_id=context.asset_id,
        asset_id=context.asset_id,
        parse_run_id=context.parse_run_id,
        doc_type="image",
        file_sha256=context.file_sha256,
        parser_name="vision+ocr" if (vision_applied and ocr_available) else "ocr" if ocr_available
        else "vision" if vision_applied else "none",
        parser_version="1",
        config_version="image-v1",
        pages=[page],
        warnings=list(page.warnings),
        page_count=1,
    )
    document.sections = build_sections(document, document_title=context.title or "图片资料")
    return document


def _image_ocr_drafts(result: object) -> list[TextBlockDraft]:
    lines = list(getattr(result, "lines", []) or [])
    ordered = sorted(
        lines,
        key=lambda line: (
            (line.bbox[1] if getattr(line, "bbox", None) else 0),
            (line.bbox[0] if getattr(line, "bbox", None) else 0),
        ),
    )
    drafts: list[TextBlockDraft] = []
    buffer: list[str] = []
    buffer_boxes: list[list[float]] = []
    heights = [
        line.bbox[3] - line.bbox[1]
        for line in lines if getattr(line, "bbox", None) and len(line.bbox) == 4
    ]
    median_height = sorted(heights)[len(heights) // 2] if heights else 0.0

    def flush() -> None:
        nonlocal buffer, buffer_boxes
        text = " ".join(part.strip() for part in buffer if part.strip()).strip()
        if not text:
            buffer, buffer_boxes = [], []
            return
        bbox = [
            min(box[0] for box in buffer_boxes), min(box[1] for box in buffer_boxes),
            max(box[2] for box in buffer_boxes), max(box[3] for box in buffer_boxes),
        ] if buffer_boxes else None
        if is_equation(text):
            drafts.append(TextBlockDraft(text=text, size=None, bold=False, bbox=bbox,
                                         kind="equation",
                                         warnings=("公式未能还原为 LaTeX，需人工核对",)))
        else:
            level = heading_level(text, size=None, bold=False, body_size=None)
            drafts.append(TextBlockDraft(
                text=text, size=None, bold=False, bbox=bbox,
                kind="heading" if level else "paragraph", level=level,
            ))
        buffer, buffer_boxes = [], []

    previous = None
    for line in ordered:
        text = str(getattr(line, "text", "") or "").strip()
        if not text:
            continue
        bbox = getattr(line, "bbox", None)
        if previous is not None and bbox and getattr(previous, "bbox", None):
            gap = bbox[1] - previous.bbox[3]
            if median_height and gap > median_height * 1.8:
                flush()
        buffer.append(text)
        if bbox:
            buffer_boxes.append(bbox)
        previous = line
    flush()
    return drafts


def _apply_vision(
    result: object, page: PageIR, blocks: list[BlockIR], context: object, *, index_base: int,
    image_key: str | None = None,
) -> bool:
    description = getattr(result, "description", None)
    latex = getattr(result, "latex", None)
    table = getattr(result, "table", None)
    figure = getattr(result, "figure", None)
    uncertain = bool(getattr(result, "uncertain", True))
    warnings = list(getattr(result, "warnings", []) or [])
    applied = False
    run_prefix = context.parse_run_id[:8]

    if isinstance(table, dict) and isinstance(table.get("rows"), list):
        rows = [[str(cell) for cell in row] for row in table["rows"] if isinstance(row, list)]
        if rows and any(any(cell.strip() for cell in row) for row in rows):
            header = table.get("header_rows") if isinstance(table.get("header_rows"), int) else 1
            blocks.append(BlockIR(
                block_id=f"{run_prefix}-p1-t{index_base + 1}", page_number=1, order=0, global_order=0,
                type="table", text="\n".join(" | ".join(row) for row in rows),
                table=TableData(rows=rows, header_rows=max(1, header)),
                source=SourceSpan(asset_id=context.asset_id, page_number=1,
                                  location_label="视觉模型识别的原始图片"),
                extraction="vision", confidence=None if uncertain else 0.75,
                warnings=warnings,
            ))
            applied = True

    if latex:
        blocks.append(BlockIR(
            block_id=f"{run_prefix}-p1-eq{index_base + 1}", page_number=1, order=0, global_order=0,
            type="equation", text=str(latex), latex=str(latex),
            source=SourceSpan(asset_id=context.asset_id, page_number=1,
                              location_label="视觉模型识别的原始图片"),
            extraction="vision", confidence=None if uncertain else 0.8,
            warnings=warnings + (["公式识别结果不确定"] if uncertain else []),
        ))
        applied = True

    if description or (isinstance(figure, dict) and (figure.get("nodes") or figure.get("edges"))):
        nodes = [str(item) for item in (figure or {}).get("nodes") or []][:60]
        edges = [str(item) for item in (figure or {}).get("edges") or []][:80]
        kind = str((figure or {}).get("kind") or "other")
        blocks.append(BlockIR(
            block_id=f"{run_prefix}-p1-f{index_base + 1}", page_number=1, order=0, global_order=0,
            type="figure", text=description or "；".join(nodes) or "图像结构",
            figure=FigureData(kind=kind, description=description, nodes=nodes, edges=edges,
                              uncertain=uncertain, image_key=image_key),
            source=SourceSpan(asset_id=context.asset_id, page_number=1,
                              location_label="视觉模型识别的原始图片"),
            extraction="vision", confidence=None if uncertain else 0.8,
            warnings=warnings + (["图形识别结果不确定"] if uncertain else []),
        ))
        applied = True

    if applied and uncertain:
        page.warnings.append("视觉识别结果标记为不确定，请核对原图")
    return applied
