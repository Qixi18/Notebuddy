"""Notebook document v2 storage contract.

The editor persists a ProseMirror/Tiptap JSON document instead of the legacy
``[{id, type, text}]`` block array.  Legacy rows are converted lazily on read;
nothing is rewritten in place.  Validation is intentionally strict: the API is
the only place that accepts a whole document tree, so it must reject anything
the editor cannot faithfully render.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 2
# Limits are sized for real migrated vaults: a course notebook with ~70 legacy
# sections is ~3.2k nodes and ~230KB, still small for SQLite/Tiptap.
MAX_NODES = 8_000
MAX_DEPTH = 12
MAX_BLOCK_TEXT = 20_000
MAX_TOTAL_TEXT = 1_000_000
MAX_DOCUMENT_BYTES = 8_000_000
MAX_BLOCK_ID = 64
MAX_ATTACHMENT_ALT = 300
MAX_LATEX = 2_000

TOP_LEVEL_TYPES = {
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "taskList",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "table",
    "callout",
    "example",
    "image",
    "blockMath",
}

ALLOWED_NODES = TOP_LEVEL_TYPES | {
    "doc",
    "text",
    "hardBreak",
    "listItem",
    "taskItem",
    "tableRow",
    "tableCell",
    "tableHeader",
    "image",
    "inlineMath",
    "blockMath",
}

INLINE_TYPES = {"text", "hardBreak", "inlineMath"}
BLOCK_TYPES = TOP_LEVEL_TYPES
LEAF_TYPES = {"text", "hardBreak", "inlineMath", "blockMath", "image", "horizontalRule"}

ALLOWED_MARKS = {"bold", "italic", "underline", "strike", "link", "code", "highlight"}

ALLOWED_ATTRS: dict[str, set[str]] = {
    "doc": set(),
    "paragraph": {"blockId", "textAlign"},
    "heading": {"blockId", "level", "textAlign"},
    "text": set(),
    "hardBreak": set(),
    "bulletList": {"blockId"},
    # Tiptap serializes the standard <ol type> attribute (null by default).
    # Keep it in the storage contract so browser round trips remain lossless.
    "orderedList": {"blockId", "start", "type"},
    "listItem": set(),
    "taskList": {"blockId"},
    "taskItem": {"checked"},
    "blockquote": {"blockId"},
    "codeBlock": {"blockId", "language"},
    "horizontalRule": set(),
    "table": {"blockId"},
    "tableRow": set(),
    "tableCell": {"colspan", "rowspan", "colwidth", "align"},
    "tableHeader": {"colspan", "rowspan", "colwidth", "align"},
    "image": {"src", "alt", "title", "attachmentId", "assetId", "width", "height"},
    "inlineMath": {"latex"},
    "blockMath": {"latex", "blockId"},
    "callout": {"blockId", "tone", "title"},
    "example": {"blockId", "title"},
}

CALLOUT_TONES = {"tip", "warning", "note"}

ATTACHMENT_SRC_RE = re.compile(r"^/api/v1/notebook-attachments/[A-Za-z0-9_-]{1,64}$")
ASSET_SRC_RE = re.compile(r"^/api/v1/assets/[A-Za-z0-9_-]{1,64}/content$")
LINK_PROTOCOL_RE = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)
ATTACHMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DocumentValidationError(ValueError):
    """Raised when a submitted document violates the storage contract."""


@dataclass
class StoredDocument:
    content: dict[str, Any]
    revision: int
    legacy: bool = False
    warning: str | None = None


def _new_block_id(prefix: str = "block") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def empty_document() -> dict[str, Any]:
    return {"type": "doc", "content": []}


# ---------------------------------------------------------------------------
# Reading and normalising stored JSON
# ---------------------------------------------------------------------------


def load_document(raw: str | None) -> StoredDocument:
    """Parse a stored ``document_json`` value, accepting legacy block arrays."""

    if raw is None or not raw.strip():
        return StoredDocument(empty_document(), 0)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return StoredDocument(empty_document(), 0, warning="笔记正文格式无法识别，已按空笔记打开。")
    if isinstance(parsed, list):
        return StoredDocument(legacy_blocks_to_document(parsed), 0, legacy=True)
    if isinstance(parsed, dict):
        if parsed.get("schema_version") == SCHEMA_VERSION and isinstance(parsed.get("doc"), dict):
            return StoredDocument(parsed["doc"], 0, legacy=parsed.get("legacy_compatible") is True)
        # An early v2 draft wrote the bare document at the top level.
        if parsed.get("type") == "doc":
            return StoredDocument(parsed, 0)
    return StoredDocument(empty_document(), 0, warning="笔记正文格式无法识别，已按空笔记打开。")


def wrap_document(content: dict[str, Any], *, legacy_compatible: bool = False) -> dict[str, Any]:
    wrapped = {"schema_version": SCHEMA_VERSION, "doc": content}
    if legacy_compatible:
        wrapped["legacy_compatible"] = True
    return wrapped


def dump_document(content: dict[str, Any], *, legacy_compatible: bool = False) -> str:
    return json.dumps(wrap_document(content, legacy_compatible=legacy_compatible),
                      ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Legacy block conversion
# ---------------------------------------------------------------------------


def legacy_blocks_to_document(blocks: list[Any]) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            continue
        block_id = _unique_id(raw.get("id"), used, fallback=f"legacy-{index + 1}")
        block_type = raw.get("type")
        text = raw.get("text")
        text = text if isinstance(text, str) else ""
        if block_type in {"h1", "h2"}:
            level = 1 if block_type == "h1" else 2
            content.append({
                "type": "heading",
                "attrs": {"level": level, "blockId": block_id},
                "content": _inline_nodes(text) if text.strip() else [],
            })
        elif block_type == "bullet":
            items = [line for line in text.split("\n") if line.strip()] or [text]
            content.append({
                "type": "bulletList",
                "attrs": {"blockId": block_id},
                "content": [
                    {"type": "listItem", "content": [
                        {"type": "paragraph", "content": _inline_nodes(item.strip())}
                    ]}
                    for item in items
                ],
            })
        else:
            nodes = markdown_to_nodes(text, block_id=block_id)
            content.extend(nodes)
    return {"type": "doc", "content": content}


def _unique_id(candidate: Any, used: set[str], *, fallback: str) -> str:
    value = candidate if isinstance(candidate, str) else ""
    value = value.strip()[:MAX_BLOCK_ID]
    if not value or value in used:
        value = fallback[:MAX_BLOCK_ID]
        suffix = 2
        while value in used:
            value = f"{fallback[:56]}-{suffix}"
            suffix += 1
    used.add(value)
    return value


# ---------------------------------------------------------------------------
# Minimal Markdown -> ProseMirror conversion for imported sections
# ---------------------------------------------------------------------------


INLINE_PATTERN = re.compile(
    r"(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|`[^`\n]+`|\$[^$\n]+\$"
    r"|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
TASK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)\s*$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def markdown_to_nodes(text: str, *, block_id: str | None = None) -> list[dict[str, Any]]:
    """Convert imported Markdown to editor nodes without external dependencies.

    Unsupported syntax falls back to literal text instead of being dropped.
    """

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    nodes: list[dict[str, Any]] = []
    index = 0
    first = True

    def with_block(node: dict[str, Any]) -> dict[str, Any]:
        nonlocal first
        attrs = dict(node.get("attrs") or {})
        if first and block_id:
            attrs["blockId"] = block_id
        if attrs or "attrs" in node:
            node = {**node, "attrs": attrs}
        first = False
        return node

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            language = fence.group(1) or None
            index += 1
            body: list[str] = []
            while index < len(lines) and not FENCE_RE.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1
            nodes.append(with_block({
                "type": "codeBlock",
                "attrs": {"language": language} if language else {},
                "content": [{"type": "text", "text": "\n".join(body)}] if body else [],
            }))
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 3)
            nodes.append(with_block({
                "type": "heading",
                "attrs": {"level": level},
                "content": _inline_nodes(heading.group(2).strip()),
            }))
            index += 1
            continue

        if re.match(r"^\s*([-*_])\s*\1\s*\1[\s\-*_]*$", line):
            nodes.append({"type": "horizontalRule"})
            first = False
            index += 1
            continue

        if TASK_RE.match(line):
            items: list[dict[str, Any]] = []
            while index < len(lines):
                task = TASK_RE.match(lines[index])
                if not task:
                    break
                items.append({
                    "type": "taskItem",
                    "attrs": {"checked": task.group(1).lower() == "x"},
                    "content": [{"type": "paragraph", "content": _inline_nodes(task.group(2).strip())}],
                })
                index += 1
            nodes.append(with_block({"type": "taskList", "content": items}))
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            items = []
            while index < len(lines):
                match = BULLET_RE.match(lines[index])
                if not match or TASK_RE.match(lines[index]):
                    break
                items.append({"type": "listItem", "content": [
                    {"type": "paragraph", "content": _inline_nodes(match.group(1).strip())}
                ]})
                index += 1
            nodes.append(with_block({"type": "bulletList", "content": items}))
            continue

        ordered = ORDERED_RE.match(line)
        if ordered:
            start = int(ordered.group(1)) or 1
            items = []
            while index < len(lines):
                match = ORDERED_RE.match(lines[index])
                if not match:
                    break
                items.append({"type": "listItem", "content": [
                    {"type": "paragraph", "content": _inline_nodes(match.group(2).strip())}
                ]})
                index += 1
            nodes.append(with_block({"type": "orderedList", "attrs": {"start": start}, "content": items}))
            continue

        if QUOTE_RE.match(line):
            quoted: list[str] = []
            while index < len(lines) and QUOTE_RE.match(lines[index]):
                quoted.append(QUOTE_RE.match(lines[index]).group(1))  # type: ignore[union-attr]
                index += 1
            nodes.append(with_block({
                "type": "blockquote",
                "content": [_paragraph(quoted)],
            }))
            continue

        if "|" in line and index + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[index + 1]):
            rows = [line]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(lines[index])
                index += 1
            table = _table_from_rows(rows)
            if table is not None:
                nodes.append(with_block(table))
                continue
            # Fall through and keep the raw text when the table is malformed.

        # Paragraph: gather until a blank line or the start of another block.
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not _starts_block(lines, index):
            paragraph.append(lines[index].strip())
            index += 1
        if not paragraph:
            paragraph.append(line.strip())
            index += 1
        nodes.append(with_block(_paragraph(paragraph)))

    return nodes


def _starts_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    if FENCE_RE.match(line) or HEADING_RE.match(line) or BULLET_RE.match(line):
        return True
    if ORDERED_RE.match(line) or QUOTE_RE.match(line):
        return True
    if re.match(r"^\s*([-*_])\s*\1\s*\1[\s\-*_]*$", line):
        return True
    return "|" in line and index + 1 < len(lines) and bool(TABLE_DIVIDER_RE.match(lines[index + 1]))


def _paragraph(lines: list[str]) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for position, line in enumerate(lines):
        if position:
            content.append({"type": "hardBreak"})
        content.extend(_inline_nodes(line))
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _table_from_rows(rows: list[str]) -> dict[str, Any] | None:
    cells = [_split_table_row(row) for row in rows]
    width = max(len(row) for row in cells)
    if width == 0:
        return None
    normalized = [row + [""] * (width - len(row)) for row in cells]
    body: list[dict[str, Any]] = []
    for row_index, row in enumerate(normalized):
        cell_type = "tableHeader" if row_index == 0 else "tableCell"
        body.append({
            "type": "tableRow",
            "content": [
                {"type": cell_type, "content": [_paragraph([value])]}
                for value in row
            ],
        })
    return {"type": "table", "content": body}


def _split_table_row(row: str) -> list[str]:
    value = row.strip()
    value = value.removeprefix("|")
    value = value.removesuffix("|")
    return [cell.strip() for cell in value.split("|")]


def _inline_nodes(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    nodes: list[dict[str, Any]] = []
    cursor = 0
    for match in INLINE_PATTERN.finditer(text):
        if match.start() > cursor:
            nodes.append({"type": "text", "text": text[cursor:match.start()]})
        token = match.group(0)
        nodes.extend(_inline_token(token))
        cursor = match.end()
    if cursor < len(text):
        nodes.append({"type": "text", "text": text[cursor:]})
    return _merge_text(nodes)


def _inline_token(token: str) -> list[dict[str, Any]]:
    if token.startswith("**") and token.endswith("**") and len(token) > 4:
        return _marked(token[2:-2], {"type": "bold"})
    if token.startswith("__") and token.endswith("__") and len(token) > 4:
        return _marked(token[2:-2], {"type": "bold"})
    if token.startswith("~~") and token.endswith("~~") and len(token) > 4:
        return _marked(token[2:-2], {"type": "strike"})
    if token.startswith("`") and token.endswith("`") and len(token) > 2:
        return _marked(token[1:-1], {"type": "code"})
    if token.startswith("$") and token.endswith("$") and len(token) > 2:
        return [{"type": "inlineMath", "attrs": {"latex": token[1:-1].strip()}}]
    if token.startswith("[") and "](" in token and token.endswith(")"):
        label, href = token[1:-1].split("](", 1)
        if LINK_PROTOCOL_RE.match(href):
            return _marked(label, {"type": "link", "attrs": {"href": href}})
        return [{"type": "text", "text": token}]
    if (token.startswith("*") and token.endswith("*") and len(token) > 2) or (
        token.startswith("_") and token.endswith("_") and len(token) > 2
    ):
        return _marked(token[1:-1], {"type": "italic"})
    return [{"type": "text", "text": token}]


def _marked(text: str, mark: dict[str, Any]) -> list[dict[str, Any]]:
    if not text:
        return []
    node: dict[str, Any] = {"type": "text", "text": text, "marks": [mark]}
    return [node]


def _merge_text(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for node in nodes:
        if (
            merged
            and node.get("type") == "text"
            and merged[-1].get("type") == "text"
            and merged[-1].get("marks") == node.get("marks")
        ):
            merged[-1]["text"] += node["text"]
        elif node.get("type") == "text" and not node.get("text"):
            continue
        else:
            merged.append(node)
    return merged


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def normalize_document(content: Any) -> dict[str, Any]:
    """Fill in missing stable block ids so the outline stays addressable."""

    if not isinstance(content, dict) or content.get("type") != "doc":
        raise DocumentValidationError("正文必须是一个文档对象")
    normalized = json.loads(json.dumps(content))
    used: set[str] = set()
    normalized["content"] = _normalize_nodes(normalized.get("content"), used)
    return normalized


def _normalize_nodes(nodes: Any, used: set[str], *, top_level: bool = True) -> list[dict[str, Any]]:
    if nodes is None:
        return []
    if not isinstance(nodes, list):
        raise DocumentValidationError("文档内容必须是节点数组")
    result: list[dict[str, Any]] = []
    for position, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise DocumentValidationError("文档节点格式不正确")
        node = json.loads(json.dumps(node))
        node_type = node.get("type")
        if top_level and node_type in TOP_LEVEL_TYPES and node_type not in {"horizontalRule", "image"}:
            attrs = node.setdefault("attrs", {})
            if not isinstance(attrs, dict):
                raise DocumentValidationError("节点属性格式不正确")
            block_id = attrs.get("blockId")
            if not isinstance(block_id, str) or not block_id.strip() or block_id in used:
                attrs["blockId"] = _new_block_id(f"block-{position + 1}")
            used.add(attrs["blockId"])
        if isinstance(node.get("content"), list):
            node["content"] = _normalize_nodes(node["content"], used, top_level=False)
        result.append(node)
    return result


def validate_document(content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict) or content.get("type") != "doc":
        raise DocumentValidationError("正文必须是一个文档对象")
    if set(content) - {"type", "content"}:
        raise DocumentValidationError("文档包含未知字段")
    counts = {"nodes": 1, "text": 0}
    children = content.get("content") or []
    if not isinstance(children, list):
        raise DocumentValidationError("文档内容必须是节点数组")
    for child in children:
        _validate_node(child, depth=2, top_level=True, counts=counts)
    encoded = json.dumps(content, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise DocumentValidationError("笔记正文数据过大")
    if counts["nodes"] > MAX_NODES:
        raise DocumentValidationError("笔记内容块过多")
    if counts["text"] > MAX_TOTAL_TEXT:
        raise DocumentValidationError("笔记正文过长")
    return content


def _validate_node(node: Any, *, depth: int, top_level: bool, counts: dict[str, int]) -> None:
    if not isinstance(node, dict):
        raise DocumentValidationError("文档节点格式不正确")
    if depth > MAX_DEPTH:
        raise DocumentValidationError("笔记内容嵌套过深")
    counts["nodes"] += 1

    node_type = node.get("type")
    if not isinstance(node_type, str) or node_type not in ALLOWED_NODES:
        raise DocumentValidationError(f"不支持的笔记节点：{node_type}")
    if top_level and node_type not in TOP_LEVEL_TYPES:
        raise DocumentValidationError(f"顶层不能使用节点：{node_type}")
    if not top_level and node_type == "image" and depth > 3:
        raise DocumentValidationError("图片节点位置不合法")
    allowed_fields = {"type", "attrs", "content"}
    if node_type == "text":
        allowed_fields.update({"text", "marks"})
    if set(node) - allowed_fields:
        raise DocumentValidationError(f"节点 {node_type} 包含未知字段")

    attrs = node.get("attrs")
    if attrs is not None and not isinstance(attrs, dict):
        raise DocumentValidationError("节点属性格式不正确")
    attrs = attrs or {}
    unknown = set(attrs) - ALLOWED_ATTRS.get(node_type, set())
    if unknown:
        raise DocumentValidationError(f"节点 {node_type} 包含未知属性")

    if node_type == "heading":
        level = attrs.get("level", 1)
        if not isinstance(level, int) or level not in (1, 2, 3):
            raise DocumentValidationError("标题层级只能是 1-3")
    if node_type == "text":
        text = node.get("text")
        if not isinstance(text, str):
            raise DocumentValidationError("文本节点缺少内容")
        if len(text) > MAX_BLOCK_TEXT:
            raise DocumentValidationError("单个文本节点过长")
        counts["text"] += len(text)
        marks = node.get("marks") or []
        if not isinstance(marks, list):
            raise DocumentValidationError("文本格式标记格式不正确")
        for mark in marks:
            _validate_mark(mark)
    if node_type == "image":
        _validate_image(attrs)
    if node_type in {"inlineMath", "blockMath"}:
        latex = attrs.get("latex")
        if not isinstance(latex, str) or not latex.strip() or len(latex) > MAX_LATEX:
            raise DocumentValidationError("公式内容不合法")
    if node_type == "callout":
        if attrs.get("tone") not in CALLOUT_TONES:
            raise DocumentValidationError("重点提示类型不合法")
        _validate_title(attrs.get("title"), "提示标题")
    if node_type == "example":
        _validate_title(attrs.get("title"), "例题标题")
    if node_type == "orderedList":
        start = attrs.get("start", 1)
        if not isinstance(start, int) or start < 1 or start > 100_000:
            raise DocumentValidationError("有序列表起始值不合法")
        list_type = attrs.get("type")
        if list_type is not None and list_type not in {"1", "a", "A", "i", "I"}:
            raise DocumentValidationError("有序列表编号样式不合法")
    if node_type == "codeBlock":
        language = attrs.get("language")
        if language is not None and (not isinstance(language, str) or len(language) > 40):
            raise DocumentValidationError("代码块语言标记不合法")
    if node_type == "taskItem" and not isinstance(attrs.get("checked"), bool):
        raise DocumentValidationError("待办状态不合法")
    if node_type in {"tableCell", "tableHeader"}:
        for name in ("colspan", "rowspan"):
            value = attrs.get(name, 1)
            if not isinstance(value, int) or value < 1 or value > 100:
                raise DocumentValidationError("表格跨度不合法")
    block_id = attrs.get("blockId")
    if block_id is not None and (not isinstance(block_id, str) or not block_id.strip()
                                 or len(block_id) > MAX_BLOCK_ID):
        raise DocumentValidationError("内容块编号不合法")

    content = node.get("content")
    _validate_children(node_type, content)
    if content is not None:
        if not isinstance(content, list):
            raise DocumentValidationError("节点内容必须是数组")
        for child in content:
            _validate_node(child, depth=depth + 1, top_level=False, counts=counts)


def _validate_children(node_type: str, content: Any) -> None:
    if node_type in LEAF_TYPES:
        if content:
            raise DocumentValidationError(f"节点 {node_type} 不能包含子节点")
        return
    if content is None:
        content = []
    if not isinstance(content, list):
        raise DocumentValidationError("节点内容必须是数组")
    children = [child.get("type") if isinstance(child, dict) else None for child in content]
    if node_type in {"paragraph", "heading"}:
        valid = all(child in INLINE_TYPES for child in children)
    elif node_type == "codeBlock":
        valid = all(child == "text" for child in children)
    elif node_type in {"bulletList", "orderedList"}:
        valid = bool(children) and all(child == "listItem" for child in children)
    elif node_type == "taskList":
        valid = bool(children) and all(child == "taskItem" for child in children)
    elif node_type in {"listItem", "taskItem"}:
        valid = bool(children) and children[0] == "paragraph" and all(
            child in BLOCK_TYPES for child in children[1:]
        )
    elif node_type == "table":
        valid = bool(children) and all(child == "tableRow" for child in children)
    elif node_type == "tableRow":
        valid = bool(children) and all(child in {"tableCell", "tableHeader"} for child in children)
    elif node_type in {"tableCell", "tableHeader", "blockquote", "callout", "example"}:
        valid = bool(children) and all(child in BLOCK_TYPES for child in children)
    else:
        valid = False
    if not valid:
        raise DocumentValidationError(f"节点 {node_type} 的子节点结构不合法")


def _validate_mark(mark: Any) -> None:
    if not isinstance(mark, dict):
        raise DocumentValidationError("文本格式标记格式不正确")
    mark_type = mark.get("type")
    if mark_type not in ALLOWED_MARKS:
        raise DocumentValidationError(f"不支持的文本格式：{mark_type}")
    attrs = mark.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise DocumentValidationError("文本格式属性不正确")
    if mark_type == "link":
        href = attrs.get("href")
        if not isinstance(href, str) or not LINK_PROTOCOL_RE.match(href) or len(href) > 2_000:
            raise DocumentValidationError("链接地址不合法")
        unknown = set(attrs) - {"href", "target", "rel", "class"}
        if unknown:
            raise DocumentValidationError("链接包含未知属性")
    elif attrs:
        raise DocumentValidationError("该文本格式不接受属性")


def _validate_image(attrs: dict[str, Any]) -> None:
    src = attrs.get("src")
    attachment_id = attrs.get("attachmentId")
    asset_id = attrs.get("assetId")
    if attachment_id is not None:
        if (not isinstance(src, str) or not ATTACHMENT_SRC_RE.match(src)
                or not isinstance(attachment_id, str) or not ATTACHMENT_ID_RE.match(attachment_id)
                or src.rsplit("/", 1)[-1] != attachment_id):
            raise DocumentValidationError("图片附件编号或地址不合法")
        if asset_id is not None:
            raise DocumentValidationError("图片不能同时使用附件编号和 Asset 编号")
    elif asset_id is not None:
        if (not isinstance(src, str) or not ASSET_SRC_RE.match(src)
                or not isinstance(asset_id, str) or not ATTACHMENT_ID_RE.match(asset_id)
                or src != f"/api/v1/assets/{asset_id}/content"):
            raise DocumentValidationError("图片资源编号或地址不合法")
    else:
        raise DocumentValidationError("图片必须引用本笔记的稳定资源编号")
    alt = attrs.get("alt", "")
    if not isinstance(alt, str) or len(alt) > MAX_ATTACHMENT_ALT:
        raise DocumentValidationError("图片说明过长")
    title = attrs.get("title")
    if title is not None and (not isinstance(title, str) or len(title) > MAX_ATTACHMENT_ALT):
        raise DocumentValidationError("图片标题过长")
    for dimension in ("width", "height"):
        value = attrs.get(dimension)
        if value is not None and (not isinstance(value, int) or value < 1 or value > 20_000):
            raise DocumentValidationError("图片尺寸不合法")


def _validate_title(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise DocumentValidationError(f"{label}不合法")


# ---------------------------------------------------------------------------
# Legacy read projection (kept for older clients during the transition)
# ---------------------------------------------------------------------------


def attachment_ids(content: dict[str, Any]) -> set[str]:
    ids: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "image":
            attrs = node.get("attrs") or {}
            for key in ("attachmentId", "assetId"):
                value = attrs.get(key)
                if isinstance(value, str):
                    ids.add(value)
        for child in node.get("content") or []:
            walk(child)

    walk(content)
    return ids


def document_to_blocks(content: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for node in content.get("content") or []:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        attrs = node.get("attrs") or {}
        block_id = attrs.get("blockId") or _new_block_id()
        if node_type == "heading":
            level = 1 if attrs.get("level", 1) == 1 else 2
            blocks.append({"id": block_id, "type": f"h{level}", "text": _plain_text(node)})
        elif node_type == "paragraph":
            text = _plain_text(node)
            if text or len(content.get("content") or []) > 1:
                blocks.append({"id": block_id, "type": "p", "text": text})
        elif node_type == "bulletList":
            for position, item in enumerate(node.get("content") or []):
                blocks.append({"id": f"{block_id}-{position + 1}", "type": "bullet",
                               "text": _plain_text(item)})
        elif node_type in TOP_LEVEL_TYPES:
            blocks.append({"id": block_id, "type": "p", "text": _plain_text(node)})
    return blocks


def _plain_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text") or "")
    if node_type == "hardBreak":
        return "\n"
    if node_type == "inlineMath":
        return f"${(node.get('attrs') or {}).get('latex', '')}$"
    if node_type == "image":
        return str((node.get("attrs") or {}).get("alt") or "")
    parts = [_plain_text(child) for child in node.get("content") or []]
    separator = "\n" if node_type in {"doc", "bulletList", "orderedList", "taskList", "table"} else ""
    return separator.join(part for part in parts if part)


def document_to_markdown(content: dict[str, Any]) -> str:
    """Export a document to Markdown, degrading unknown nodes to readable text."""

    lines: list[str] = []
    for node in content.get("content") or []:
        lines.extend(_node_markdown(node, indent=0))
        lines.append("")
    return "\n".join(lines).strip() + "\n" if lines else ""


def _node_markdown(node: Any, *, indent: int) -> list[str]:
    if not isinstance(node, dict):
        return []
    pad = "  " * indent
    node_type = node.get("type")
    attrs = node.get("attrs") or {}
    if node_type == "heading":
        level = max(1, min(int(attrs.get("level", 1)), 6))
        return [f"{'#' * level} {_inline_markdown(node)}"]
    if node_type == "paragraph":
        return [f"{pad}{_inline_markdown(node)}"]
    if node_type == "bulletList":
        result: list[str] = []
        for item in node.get("content") or []:
            children = _node_markdown(item, indent=indent + 1)
            if children:
                result.append(f"{pad}- {children[0].strip()}")
                result.extend(children[1:])
        return result
    if node_type == "orderedList":
        result = []
        for position, item in enumerate(node.get("content") or []):
            children = _node_markdown(item, indent=indent + 1)
            if children:
                result.append(f"{pad}{position + 1}. {children[0].strip()}")
                result.extend(children[1:])
        return result
    if node_type == "taskList":
        result = []
        for item in node.get("content") or []:
            checked = "x" if (item.get("attrs") or {}).get("checked") else " "
            children = _node_markdown(item, indent=indent + 1)
            if children:
                result.append(f"{pad}- [{checked}] {children[0].strip()}")
                result.extend(children[1:])
        return result
    if node_type == "blockquote":
        quoted = []
        for child in node.get("content") or []:
            quoted.extend(_node_markdown(child, indent=0))
        return [f"{pad}> {line}" if line else f"{pad}>" for line in quoted]
    if node_type == "codeBlock":
        language = attrs.get("language") or ""
        return [f"{pad}```{language}", _plain_text(node), f"{pad}```"]
    if node_type == "horizontalRule":
        return [f"{pad}---"]
    if node_type == "table":
        rows = []
        for row in node.get("content") or []:
            cells = [_inline_markdown(cell).replace("|", "\\|") for cell in row.get("content") or []]
            rows.append("| " + " | ".join(cells) + " |")
        if rows:
            divider = "| " + " | ".join("---" for _ in (node.get("content") or [{}])[0].get("content") or []) + " |"
            return [rows[0], divider, *rows[1:]]
        return []
    if node_type == "callout":
        title = attrs.get("title") or "重点提示"
        body = []
        for child in node.get("content") or []:
            body.extend(_node_markdown(child, indent=0))
        return [f"> **{title}**", *[f"> {line}" for line in body]]
    if node_type == "example":
        title = attrs.get("title") or "例题"
        body = []
        for child in node.get("content") or []:
            body.extend(_node_markdown(child, indent=0))
        return [f"**{title}**", *body]
    if node_type in {"inlineMath", "blockMath"}:
        return [f"$${attrs.get('latex', '')}$$"]
    if node_type == "image":
        return [f"![{attrs.get('alt', '')}]({attrs.get('src', '')})"]
    return [f"{pad}{_plain_text(node)}"]


def _inline_markdown(node: Any) -> str:
    parts: list[str] = []
    for child in node.get("content") or []:
        child_type = child.get("type")
        if child_type == "text":
            text = str(child.get("text") or "")
            for mark in reversed(child.get("marks") or []):
                mark_type = mark.get("type")
                text = {
                    "bold": f"**{text}**",
                    "italic": f"*{text}*",
                    "strike": f"~~{text}~~",
                    "code": f"`{text}`",
                    "underline": f"<u>{text}</u>",
                    "highlight": f"=={text}==",
                }.get(mark_type, text)
                if mark_type == "link":
                    text = f"[{text}]({(mark.get('attrs') or {}).get('href', '')})"
            parts.append(text)
        elif child_type == "hardBreak":
            parts.append("  \n")
        elif child_type == "inlineMath":
            parts.append(f"${(child.get('attrs') or {}).get('latex', '')}$")
        elif child_type == "image":
            parts.append(f"![{(child.get('attrs') or {}).get('alt', '')}]({(child.get('attrs') or {}).get('src', '')})")
        else:
            parts.append(_plain_text(child))
    return "".join(parts)
