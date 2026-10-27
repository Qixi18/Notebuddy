"""Shared text heuristics for turning raw spans/lines into IR blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.document_processing.engines.pdf_text import RawLine, RawSpan, RawTextBlock
from app.document_processing.ir import BlockIR, SourceSpan
from app.document_processing.normalization.sections import heading_level_from_numbering

MATH_CHARS = set("=+-−×÷∑∏∫√∞≤≥≈≠∈∉⊂⊃⊆⊇→←↔∂∇°′″±∓⋅·^_{}|[]()<>/\\%")
GREEK = set("αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")
CJK = re.compile(r"[\u4e00-\u9fff]")
LIST_PREFIX = re.compile(r"^\s*(?:[-•·●▪◦]|\(?\d+[.)、）]|[一二三四五六七八九十]+[、.)）])\s*")
SENTENCE_END = ("。", "！", "？", "；", ".", "!", "?", ";", ":", "：")


@dataclass
class TextBlockDraft:
    text: str
    size: float | None
    bold: bool
    bbox: list[float] | None
    kind: str = "paragraph"
    level: int = 0
    latex: str | None = None
    warnings: tuple[str, ...] = ()


def join_spans(spans: list[RawSpan]) -> str:
    parts: list[str] = []
    for span in spans:
        text = span.text
        if not text:
            continue
        if parts and _needs_space(parts[-1], text):
            parts.append(" ")
        parts.append(text)
    return "".join(parts).strip()


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left[-1].isspace() or right[0].isspace():
        return False
    if CJK.match(left[-1]) or CJK.match(right[0]):
        return False
    return left[-1].isalnum() and right[0].isalnum()


def join_lines(lines: list[RawLine]) -> str:
    parts: list[str] = []
    for line in lines:
        text = join_spans(line.spans)
        if not text:
            continue
        if parts and not CJK.match(parts[-1][-1:]) and parts[-1][-1:] not in "-—/":
            parts.append(" ")
        parts.append(text)
    joined = "".join(parts).strip()
    # Hyphenated line break: "exam-\nple" -> "example" (Latin only).
    return re.sub(r"(?<=[a-z])-\s+(?=[a-z])", "", joined)


def block_body_size(blocks: list[RawTextBlock]) -> float | None:
    weighted: dict[float, int] = {}
    for block in blocks:
        for line in block.lines:
            for span in line.spans:
                if span.size and span.text.strip():
                    key = round(float(span.size), 1)
                    weighted[key] = weighted.get(key, 0) + len(span.text.strip())
    if not weighted:
        return None
    return max(weighted.items(), key=lambda item: item[1])[0]


def block_lines(raw: RawTextBlock) -> tuple[str, float | None, bool]:
    text = join_lines(raw.lines)
    sizes: list[float] = []
    bold_chars = 0
    total = 0
    for line in raw.lines:
        for span in line.spans:
            if span.size:
                sizes.append(float(span.size))
            length = len(span.text.strip())
            total += length
            if span.bold:
                bold_chars += length
    size = max(sizes) if sizes else None
    bold = total > 0 and bold_chars / total >= 0.6
    return text, size, bold


def math_ratio(text: str) -> float:
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return 0.0
    math = sum(1 for char in stripped if char in MATH_CHARS or char in GREEK)
    return math / len(stripped)


def is_equation(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return False
    ratio = math_ratio(stripped)
    if CJK.search(stripped):
        return False
    # Prose with a couple of parentheses/equals signs is not an equation.
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    if len(words) >= 2 and ratio < 0.35:
        return False
    if ratio >= 0.22:
        return True
    return ratio >= 0.12 and any(token in stripped for token in ("=", "∫", "∑", "√", "→"))


def heading_level(text: str, *, size: float | None, bold: bool, body_size: float | None) -> int:
    stripped = text.strip()
    if not stripped or len(stripped) > 90:
        return 0
    if stripped.endswith(SENTENCE_END):
        return 0
    numbered = heading_level_from_numbering(stripped)
    if numbered:
        return numbered
    if body_size and size:
        ratio = float(size) / body_size
        if ratio >= 1.45 and len(stripped) <= 60:
            return 1
        if ratio >= 1.18 and len(stripped) <= 60:
            return 2
    if bold and len(stripped) <= 40 and len(stripped.split()) <= 12:
        return 3
    return 0


def looks_like_list(text: str) -> bool:
    return bool(LIST_PREFIX.match(text))


def strip_list_prefix(text: str) -> str:
    return LIST_PREFIX.sub("", text, count=1).strip()


def text_drafts(raw: RawTextBlock, *, body_size: float | None) -> list[TextBlockDraft]:
    """Split one raw text block into paragraph/heading/list/code/equation drafts."""

    text, size, bold = block_lines(raw)
    if not text:
        return []
    if is_equation(text):
        return [TextBlockDraft(text=text, size=size, bold=bold, bbox=raw.bbox,
                               kind="equation", warnings=("公式未能还原为 LaTeX，需人工核对",))]
    level = heading_level(text, size=size, bold=bold, body_size=body_size)
    if level:
        return [TextBlockDraft(text=text, size=size, bold=bold, bbox=raw.bbox,
                               kind="heading", level=level)]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1 and all(looks_like_list(line) for line in lines):
        return [TextBlockDraft(text="\n".join(strip_list_prefix(line) for line in lines),
                               size=size, bold=bold, bbox=raw.bbox, kind="list")]
    return [TextBlockDraft(text=text, size=size, bold=bold, bbox=raw.bbox)]


def make_block(
    draft: TextBlockDraft,
    *,
    block_id: str,
    page_number: int,
    order: int,
    global_order: int,
    asset_id: str,
    extraction: str,
    confidence: float | None,
    render_key: str | None = None,
) -> BlockIR:
    return BlockIR(
        block_id=block_id,
        page_number=page_number,
        order=order,
        global_order=global_order,
        type=draft.kind,
        level=draft.level,
        text=draft.text,
        latex=draft.latex,
        bbox=draft.bbox,
        source=SourceSpan(asset_id=asset_id, page_number=page_number, bbox=draft.bbox,
                          render_key=render_key),
        extraction=extraction,
        confidence=confidence,
        warnings=list(draft.warnings),
    )


def normalize_heading_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()
