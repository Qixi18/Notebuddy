"""Structured edit proposals against a Notebook document.

The agent never writes the body directly: it submits operations which are
applied to a copy of the current document and stored as a pending suggestion.
Accepting a suggestion goes through the same CAS write path as manual saves.
"""

from __future__ import annotations

from typing import Any

from app.notes.document import (
    DocumentValidationError,
    markdown_to_nodes,
    normalize_document,
    validate_document,
)

MAX_EDITS = 8


class EditRejected(ValueError):
    pass


def _section_index(nodes: list[dict[str, Any]], anchor: str) -> tuple[int, int] | None:
    wanted = " ".join(anchor.split()).casefold()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or node.get("type") != "heading":
            continue
        text = _plain(node).strip()
        if " ".join(text.split()).casefold() != wanted:
            continue
        end = index + 1
        while end < len(nodes) and not (
            isinstance(nodes[end], dict) and nodes[end].get("type") == "heading"
        ):
            end += 1
        return index, end
    return None


def _plain(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    if node.get("type") == "inlineMath":
        return f"${(node.get('attrs') or {}).get('latex', '')}$"
    if node.get("type") == "blockMath":
        return f"$${(node.get('attrs') or {}).get('latex', '')}$$"
    return "".join(_plain(child) for child in node.get("content") or [])


def _markdown_nodes(markdown: str) -> list[dict[str, Any]]:
    text = (markdown or "").strip()
    if not text:
        return []
    nodes = markdown_to_nodes(text)
    return [node for node in nodes if isinstance(node, dict)]


def apply_edits(content: dict[str, Any], edits: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise EditRejected(f"edits 必须是 1-{MAX_EDITS} 个操作")
    document = normalize_document(content)
    nodes = list(document.get("content") or [])
    for edit in edits:
        if not isinstance(edit, dict):
            raise EditRejected("操作必须是对象")
        op = edit.get("op")
        if op == "append":
            nodes.extend(_markdown_nodes(str(edit.get("content") or "")))
            continue
        anchor = str(edit.get("anchor") or "").strip()
        target = _section_index(nodes, anchor) if anchor else None
        if target is None:
            raise EditRejected(f"找不到标题为「{anchor or '（空）'}」的小节")
        start, end = target
        if op == "insert_after_heading":
            additions = _markdown_nodes(str(edit.get("content") or ""))
            nodes[end:end] = additions
        elif op == "replace_section":
            additions = _markdown_nodes(str(edit.get("content") or ""))
            nodes[start + 1:end] = additions
        elif op == "remove_section":
            del nodes[start:end]
        else:
            raise EditRejected(f"不支持的操作：{op}")
    final = validate_document(normalize_document({"type": "doc", "content": nodes}))
    if not any(_plain(node).strip() for node in final.get("content") or []):
        raise EditRejected("修改后的正文为空，已拒绝")
    return final


def count_ops(edits: list[dict[str, Any]]) -> str:
    return "、".join(str(edit.get("op")) for edit in edits if isinstance(edit, dict))


__all__ = ["DocumentValidationError", "EditRejected", "apply_edits", "count_ops"]
