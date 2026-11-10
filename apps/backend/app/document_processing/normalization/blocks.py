"""Bounded, lossless source blocks before persistence, with real provenance IDs."""
from __future__ import annotations

import hashlib
from dataclasses import replace

from app.document_processing.ir import BlockIR, DocumentIR, TableData

STANDARD_BLOCK_CHARS = 2_000


def text_parts(text: str, limit: int = STANDARD_BLOCK_CHARS) -> list[str]:
    """Prefer sentence/line boundaries without stripping or losing characters."""
    parts = []
    while len(text) > limit:
        end = max(text.rfind(separator, limit // 2, limit) + len(separator)
                  for separator in ("\n", "。", ". ", "; ", " "))
        if end < limit // 2:
            end = limit
        parts.append(text[:end])
        text = text[end:]
    if text:
        parts.append(text)
    return parts


def _parts(block: BlockIR) -> list[BlockIR]:
    if block.type == "table" and block.table:
        rows = block.table.rows
        header_count = max(0, min(block.table.header_rows, len(rows)))
        headers, body = rows[:header_count], rows[header_count:]
        groups, current = [], list(headers)
        size = sum(sum(len(cell) for cell in row) for row in headers)
        header_size = size
        for row in body:
            extra = sum(len(cell) for cell in row) + len(row) * 3
            if len(current) > header_count and size + extra > STANDARD_BLOCK_CHARS:
                groups.append(current)
                current, size = list(headers), header_size
            current.append(row)
            size += extra
        if current:
            groups.append(current)
        if len(groups) < 2:
            return [block]
        return [replace(block, table=TableData(rows=rows, header_rows=header_count),
                        text="\n".join(" | ".join(row) for row in rows)) for rows in groups]
    if block.type in {"paragraph", "caption", "list", "list_item", "code", "unknown"}:
        parts = text_parts(block.text)
        if len(parts) > 1:
            return [replace(block, text=text) for text in parts]
    return [block]


def normalize_standard_blocks(document: DocumentIR) -> None:
    """Split once before IR persistence; all fragments become actual source rows."""
    global_order = 0
    used = {block.block_id for block in document.all_blocks()}
    for page in document.pages:
        normalized = []
        for block in page.blocks:
            fragments = _parts(block)
            for index, fragment in enumerate(fragments):
                if len(fragments) > 1:
                    salt = 0
                    while True:
                        digest = hashlib.sha256(f"{block.block_id}:{index}:{salt}".encode()).hexdigest()[:24]
                        block_id = f"{block.block_id[:30]}-part-{digest}"
                        if block_id not in used:
                            break
                        salt += 1
                    used.add(block_id)
                    fragment = replace(fragment, block_id=block_id)
                normalized.append(replace(fragment, order=len(normalized), global_order=global_order))
                global_order += 1
        page.blocks = normalized
