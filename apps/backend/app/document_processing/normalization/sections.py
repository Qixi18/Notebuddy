"""Group IR blocks into cross-page sections.

Pages are source-location units; a section may span several pages.  When a
document has no headings at all we create bounded pseudo-sections so generation
input can be chunked without treating a page as a teaching unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.document_processing.ir import BlockIR, DocumentIR, PageIR, SectionIR

PSEUDO_SECTION_CHARS = 6_000
MAX_SECTIONS = 400

_NUMBERING = re.compile(r"^(?P<num>\d+(?:[.．]\d+)*)[.．、)）]?\s+")


@dataclass
class _Draft:
    title: str
    level: int
    blocks: list[BlockIR] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(block.text.strip()) for block in self.blocks)


def _flatten(pages: list[PageIR]) -> list[BlockIR]:
    blocks: list[BlockIR] = []
    for page in sorted(pages, key=lambda item: item.page_number):
        blocks.extend(sorted(page.blocks, key=lambda item: (item.order, item.global_order)))
    return [block for block in blocks if block.text.strip() or block.table or block.figure or block.type == "image"]


def heading_level_from_numbering(text: str) -> int | None:
    match = _NUMBERING.match(text.strip())
    if not match:
        return None
    depth = match.group("num").replace("．", ".").count(".") + 1
    return max(1, min(depth, 3))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def build_sections(document: DocumentIR, *, document_title: str = "") -> list[SectionIR]:
    blocks = _flatten(document.pages)
    if not blocks:
        return []

    drafts: list[_Draft] = []
    current = _Draft(title=(document_title.strip() or "文档开头"), level=0)
    headings = [block for block in blocks if block.type == "heading" and block.text.strip()]

    if not headings:
        # No heading structure: split by size at block boundaries.
        for block in blocks:
            if current.blocks and current.chars + len(block.text) > PSEUDO_SECTION_CHARS:
                drafts.append(current)
                current = _Draft(title=f"第 {len(drafts) + 1} 部分", level=0)
            current.blocks.append(block)
        drafts.append(current)
        return _finish(drafts)

    seen_titles: set[str] = set()
    for block in blocks:
        if block.type != "heading" or not block.text.strip():
            current.blocks.append(block)
            continue
        title = block.text.strip()
        key = _normalized(title)
        if key in seen_titles and current.level and len(title) < 60:
            # Repeated running header on a new page: keep it as content, do not
            # start another section with the same title.
            current.blocks.append(block)
            continue
        seen_titles.add(key)
        level = block.level or heading_level_from_numbering(title) or 1
        if current.blocks:
            drafts.append(current)
        current = _Draft(title=title, level=max(1, min(level, 3)))
        current.blocks.append(block)
    if current.blocks:
        drafts.append(current)

    # A leading "文档开头" draft is only useful when it actually has content.
    drafts = [draft for draft in drafts if draft.blocks]
    return _finish(drafts)


def _finish(drafts: list[_Draft]) -> list[SectionIR]:
    sections: list[SectionIR] = []
    for order, draft in enumerate(drafts[:MAX_SECTIONS]):
        if not draft.blocks:
            continue
        pages = [block.page_number for block in draft.blocks]
        sections.append(SectionIR(
            section_id=f"sec-{order + 1}",
            order=order,
            title=draft.title,
            level=draft.level,
            page_start=min(pages),
            page_end=max(pages),
            block_ids=[block.block_id for block in draft.blocks],
        ))
    return sections


def section_text(document: DocumentIR, section: SectionIR) -> str:
    by_id = {block.block_id: block for block in document.all_blocks()}
    parts = []
    for block_id in section.block_ids:
        block = by_id.get(block_id)
        if block is None:
            continue
        text = block.text.strip()
        if text:
            parts.append(text)
    return "\n".join(parts)
