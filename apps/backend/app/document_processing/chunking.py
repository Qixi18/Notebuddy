"""Build retrieval chunks from the IR.

Chunks are a rebuildable derived view.  They are grouped by section (never by
page alone) and keep page/block provenance so a search hit can point back to
the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.document_processing.ir import BlockIR, DocumentIR, SectionIR

DEFAULT_MAX_CHARS = 1_200
DEFAULT_MIN_CHARS = 40


@dataclass
class ChunkDraft:
    order: int
    section_id: str | None
    text: str
    page_numbers: list[int] = field(default_factory=list)
    block_ids: list[str] = field(default_factory=list)


def build_chunks(
    document: DocumentIR,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[ChunkDraft]:
    by_id = {block.block_id: block for block in document.all_blocks()}
    groups: list[tuple[SectionIR | None, list[BlockIR]]] = []
    if document.sections:
        for section in sorted(document.sections, key=lambda item: item.order):
            blocks = [by_id[block_id] for block_id in section.block_ids if block_id in by_id]
            groups.append((section, blocks))
    else:
        groups.append((None, sorted(document.all_blocks(), key=lambda item: item.global_order)))

    chunks: list[ChunkDraft] = []
    for section, blocks in groups:
        prefix = f"【{section.title}】\n" if section and section.title else ""
        current_text = prefix
        current_pages: set[int] = set()
        current_blocks: list[str] = []
        current_len = len(prefix)
        current_has_short_evidence = False

        def flush(section=section, prefix=prefix) -> None:
            nonlocal current_text, current_pages, current_blocks, current_len
            nonlocal current_has_short_evidence
            text = current_text.strip()
            if len(text) >= min_chars or (text and current_has_short_evidence):
                chunks.append(ChunkDraft(
                    order=len(chunks),
                    section_id=section.section_id if section else None,
                    text=text,
                    page_numbers=sorted(current_pages),
                    block_ids=list(current_blocks),
                ))
            current_text = prefix
            current_pages = set()
            current_blocks = []
            current_len = len(prefix)
            current_has_short_evidence = False

        for block in blocks:
            piece = block.searchable_text()
            if not piece and block.type in {"figure", "image"} and block.figure and block.figure.image_key:
                # This is an evidence locator, not a claim about image meaning.
                piece = f"第 {block.page_number} 页有未解读图像证据，请查看原图。"
            if not piece:
                continue
            for part in _split_oversized(piece, max_chars):
                addition = part + "\n"
                if current_blocks and current_len + len(addition) > max_chars:
                    flush()
                current_text += addition
                current_len += len(addition)
                current_pages.add(block.page_number)
                if block.block_id not in current_blocks:
                    current_blocks.append(block.block_id)
                if block.type == "equation" or block.type in {"figure", "image"}:
                    current_has_short_evidence = True
        flush()
    return chunks


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars * 2:
        return [text]
    parts: list[str] = []
    buffer: list[str] = []
    length = 0
    for line in text.splitlines():
        if length + len(line) + 1 > max_chars and buffer:
            parts.append("\n".join(buffer))
            buffer, length = [], 0
        buffer.append(line)
        length += len(line) + 1
    if buffer:
        parts.append("\n".join(buffer))
    return parts or [text]
