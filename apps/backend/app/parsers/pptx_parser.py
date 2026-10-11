from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.parsers.base import PARSER_VERSION, ParsedDocument
from app.parsers.base import ParsedBlock as DocumentBlock
from app.parsers.base import ParsedPage as DocumentPage

# 页脚/装饰带：通常是贴底的一整条窄文本框，字号极小，内容是
# 「曾智 (北邮 AI 学院)  向量与空间  2026 年 9 月 18 日  3 / 45」这类
# 重复出现的讲者信息与页码。它们不是知识点内容，必须剔除，
# 否则会污染每一页的正文，并被误当成「标题」（早期版本即如此）。
FOOTER_MAX_FONT_PT = 6.0
FOOTER_MAX_HEIGHT_RATIO = 0.08  # 高度小于幻灯片 8% 的贴底文本条视为页脚

# 页码样式：「3 / 45」「第 3 页」
_PAGE_COUNTER_RE = re.compile(r"\b\d+\s*/\s*\d+\b|第\s*\d+\s*页")
# 页脚里常见的分隔装饰符，如 ",   ·  ,   ·        ="
_DECORATION_RE = re.compile(r"^[\s,，.。·・=＝\-—_*+~`^|/\\:：;；()（）\[\]【】<>《》\t]+$")


class ParsedBlock(TypedDict):
    block_type: str
    content: str
    position: int
    font_size: float | None
    is_bold: bool
    object_id: str | None
    location_label: str
    extraction_method: str
    confidence: float
    warning: str | None
    top: int | None
    height: int | None


class ParsedPage(TypedDict):
    page_number: int
    title: str | None
    raw_text: str
    warning: str | None
    blocks: list[ParsedBlock]
    location_type: str
    location_label: str
    stable_location_key: str
    extraction_method: str
    confidence: float


def _shape_font_size(shape: object) -> float | None:
    text_frame = getattr(shape, "text_frame", None)
    if text_frame is None:
        return None
    values: list[float] = []
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size is not None:
                values.append(float(run.font.size.pt))
    return max(values) if values else None


def _shape_is_bold(shape: object) -> bool:
    text_frame = getattr(shape, "text_frame", None)
    if text_frame is None:
        return False
    return any(
        run.font.bold is True for paragraph in text_frame.paragraphs for run in paragraph.runs
    )


def _is_placeholder(shape: object, *types: str) -> bool:
    """判断形状是否为指定类型的占位符（标题框通常是 TITLE / CENTER_TITLE）。"""
    if not getattr(shape, "is_placeholder", False):
        return False
    try:
        name = str(shape.placeholder_format.type)
    except (AttributeError, ValueError):
        return False
    return any(token in name for token in types)


def _is_footer_shape(shape: object, slide_height: int) -> bool:
    """识别贴底的页脚/装饰带。

    两个必要特征同时满足才判定为页脚，避免误伤正文：
    1. 位于幻灯片下半部偏底处（上边缘超过 75% 高度）；
    2. 要么字号极小，要么高度很窄。
    """
    top = getattr(shape, "top", None)
    if top is None or slide_height <= 0:
        return False
    if top < slide_height * 0.75:
        return False

    height = getattr(shape, "height", None) or 0
    if height and height <= slide_height * FOOTER_MAX_HEIGHT_RATIO:
        return True

    font_size = _shape_font_size(shape)
    return font_size is not None and font_size <= FOOTER_MAX_FONT_PT


def _strip_footer_lines(text: str) -> str:
    """从多行文本里剔除混入的页脚行。

    作者常把正文框与页脚框叠在一起，导致同一 shape 的 text 里
    正文与页脚连成一片。按行清理：丢弃页码行、纯装饰行，
    以及同时含「/ 总页数」与讲者信息的行。
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        has_counter = bool(_PAGE_COUNTER_RE.search(stripped))
        if has_counter and ("/" in stripped or "页" in stripped):
            # 形如 "曾智 (北邮 AI 学院) 向量与空间 2026 年 9 月 18 日 3 / 45"
            continue
        if _DECORATION_RE.match(stripped):
            continue
        # 单个字符的装饰性残留（如孤立的全角等号）
        if len(stripped) <= 2 and _DECORATION_RE.match(stripped * 2):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _extract_page_title(blocks: list[ParsedBlock], slide_height: int) -> str | None:
    """挑选页面的真实标题。

    优先级：
    1. PPTX 标题占位符（最可靠的语义信号）；
    2. 位于版面上方的「页眉带」——这类形状的 top 常为 0 或略负
       （浮在画布上沿之外），高度窄而固定，内容是每页重复的章节名；
    3. 兜底：字号最大且位置最靠上的文本块。

    早期版本假设「第一个 shape 就是标题」，结果把装饰形状当成了标题
    （见本次上传失败的分析）；单纯按字号排序也会误取正文字号更大的页面
    （正文 16pt > 页眉 14pt），故必须先识别页眉带。
    """
    for block in blocks:
        if block["block_type"] == "title":
            return _first_line(block["content"])

    header_band = _find_header_band(blocks, slide_height)
    if header_band is not None:
        return _first_line(header_band["content"])

    candidates = [b for b in blocks if b["content"]]
    if not candidates:
        return None

    def sort_key(block: ParsedBlock) -> tuple[float, int]:
        return (-(block["font_size"] or 0.0), len(block["content"]))

    return _first_line(min(candidates, key=sort_key)["content"])


def _first_line(text: str, limit: int = 120) -> str | None:
    """取标题形状的首行——页眉带常把章节名与小节名叠成多行。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return None


def _find_header_band(blocks: list[ParsedBlock], slide_height: int) -> ParsedBlock | None:
    """找出位于版面上沿、高度窄小的页眉带（章节标题所在形状）。

    判据：top 处于幻灯片顶部区域（含略负，即浮出上沿），且高度不超过
    幻灯片高度的约 1/5。多个候选时取最靠上者。
    """
    if slide_height <= 0:
        return None
    threshold = slide_height * 0.2
    bands = [
        block
        for block in blocks
        if block["content"]
        and block["top"] is not None
        and block["top"] <= threshold
        and (block["height"] or 0) > 0
        and (block["height"] or 0) <= slide_height * 0.2
    ]
    if not bands:
        return None
    return min(bands, key=lambda block: block["top"] or 0)


def parse_pptx(path: Path) -> list[ParsedPage]:
    return [_as_legacy_page(page) for page in parse_pptx_document(path).pages]


def parse_pptx_document(path: Path) -> ParsedDocument:
    presentation = Presentation(path)
    pages: list[DocumentPage] = []
    document_warnings: list[str] = []
    slide_height = int(presentation.slide_height or 0)

    for page_number, slide in enumerate(presentation.slides, start=1):
        blocks: list[DocumentBlock] = []
        page_warnings: list[str] = []
        for position, shape in enumerate(slide.shapes):
            text = getattr(shape, "text", "")
            block_type = "title" if position == 0 else "text"
            warning = None
            if getattr(shape, "has_table", False):
                block_type = "table"
                rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in shape.table.rows]
                text = "\n".join(row for row in rows if row.strip())
            elif getattr(shape, "shape_type", None) in {
                MSO_SHAPE_TYPE.PICTURE,
                MSO_SHAPE_TYPE.GROUP,
                MSO_SHAPE_TYPE.CHART,
                MSO_SHAPE_TYPE.TABLE,
                MSO_SHAPE_TYPE.MEDIA,
            }:
                block_type = "image_or_object"
                warning = "图片、公式或复杂对象未提取为文字；可按需启用 OCR"
            if not isinstance(text, str) or not text.strip():
                if warning:
                    blocks.append(DocumentBlock(
                        block_type=block_type,
                        content="",
                        position=position,
                        object_id=str(getattr(shape, "shape_id", position)),
                        location_label=f"第 {page_number} 页 · 对象 {position + 1}",
                        extraction_method="unavailable",
                        confidence=0.0,
                        warning=warning,
                    ))
                    page_warnings.append(warning)
                continue

            cleaned = _strip_footer_lines(text)
            if not cleaned:
                # 整块都是页脚/装饰，跳过
                continue

            if getattr(shape, "has_table", False):
                block_type = "table"
            elif _is_placeholder(shape, "TITLE", "CENTER_TITLE"):
                block_type = "title"
            elif _is_footer_shape(shape, slide_height):
                # 贴底窄条仍可能有少量正文，降级为 text 但保留内容
                block_type = "text"
            else:
                block_type = "text"

            blocks.append(
                DocumentBlock(block_type=block_type, content=cleaned, position=position,
                              object_id=str(getattr(shape, "shape_id", position)),
                              location_label=f"第 {page_number} 页 · 对象 {position + 1}",
                              font_size=_shape_font_size(shape), is_bold=_shape_is_bold(shape),
                              top=getattr(shape, "top", None),
                              height=getattr(shape, "height", None),
                              extraction_method="table_parse" if block_type == "table" else "native_text",
                              confidence=1.0, warning=warning)
            )

        raw_text = "\n\n".join(block.content for block in blocks)
        pages.append(
            DocumentPage(page_number=page_number,
                         title=_extract_page_title([
                             {
                                 "block_type": block.block_type,
                                 "content": block.content,
                                 "position": block.position,
                                 "font_size": block.font_size,
                                 "is_bold": block.is_bold,
                                 "top": block.top,
                                 "height": block.height,
                             }
                             for block in blocks
                         ], slide_height),
                         raw_text=raw_text, location_type="page",
                         location_label=f"第 {page_number} 页",
                         stable_location_key=f"slide:{page_number}",
                         warning=("；".join(dict.fromkeys(page_warnings)) if page_warnings else
                                  ("本页没有识别到文本内容，建议按需 OCR" if not any(block.content for block in blocks) else None)),
                         extraction_method="native_text", confidence=1.0,
                         blocks=blocks)
        )
        if not any(block.content for block in blocks):
            document_warnings.append(f"第 {page_number} 页没有识别到文本")
        document_warnings.extend(page_warnings)

    return ParsedDocument(format="pptx", parser_version=PARSER_VERSION, pages=pages,
                          warnings=document_warnings)


def _as_legacy_page(page: DocumentPage) -> ParsedPage:
    return {
        "page_number": page.page_number,
        "title": page.title,
        "raw_text": page.raw_text,
        "warning": page.warning,
        "blocks": [
            {
                "block_type": block.block_type,
                "content": block.content,
                "position": block.position,
                "font_size": block.font_size,
                "is_bold": block.is_bold,
                "object_id": block.object_id,
                "location_label": block.location_label or "",
                "extraction_method": block.extraction_method,
                "confidence": block.confidence or 1.0,
                "warning": block.warning,
            }
            for block in page.blocks
        ],
        "location_type": page.location_type,
        "location_label": page.location_label or "",
        "stable_location_key": page.stable_location_key,
        "extraction_method": page.extraction_method,
        "confidence": page.confidence or 1.0,
    }
