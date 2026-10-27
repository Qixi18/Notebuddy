"""Compose a validated Tiptap fragment from planned knowledge units.

Two providers are supported:

- ``deepseek``: the model writes the teaching content but must return a
  ``sources`` map from every generated block to IR block ids.
- ``offline-extractive``: a deterministic, clearly-labelled composer used for
  tests/local verification without model calls.  It arranges the source content
  into headings/paragraphs/lists/tables/equations and never invents facts.

Both produce the same contract: top-level nodes + ``blockId -> IR block ids``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.ai.deepseek import DeepSeekClient, DeepSeekError

MAX_PARAGRAPH_CHARS = 1_000
MAX_TEXT_NODE = 8_000


class CompositionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "composition_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Composition:
    nodes: list[dict[str, Any]]
    source_map: dict[str, list[str]] = field(default_factory=dict)
    generator: str = "offline-extractive"
    generator_version: str = "1"
    warnings: list[str] = field(default_factory=list)


def compose(
    snapshot: dict[str, Any],
    plan: dict[str, Any],
    unit_ids: list[str],
    *,
    generator: str,
) -> Composition:
    if generator == "offline-extractive":
        return compose_offline(snapshot, plan, unit_ids)
    if generator == "deepseek":
        return compose_deepseek(snapshot, plan, unit_ids)
    raise CompositionError(f"未知生成器：{generator}", code="generator_unknown")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _block_id(prefix: str = "ai") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def _text_node(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text[:MAX_TEXT_NODE]}


def paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "attrs": {"blockId": _block_id()}, "content": [_text_node(text)]}


def heading(text: str, level: int) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"blockId": _block_id(), "level": max(1, min(level, 3))},
        "content": [_text_node(text[:300])],
    }


def bullet_list(items: list[str]) -> dict[str, Any]:
    return {
        "type": "bulletList",
        "attrs": {"blockId": _block_id()},
        "content": [{
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [_text_node(item)]}],
        } for item in items if item.strip()],
    }


def table_node(rows: list[list[str]], header_rows: int = 1) -> dict[str, Any]:
    rows = [row for row in rows if row]
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return paragraph("（表格为空）")
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header_index = max(0, min(header_rows - 1, len(normalized) - 1))
    body = []
    for index, row in enumerate(normalized):
        cell_type = "tableHeader" if index == header_index else "tableCell"
        body.append({
            "type": "tableRow",
            "content": [
                {"type": cell_type, "content": [{"type": "paragraph", "content": [_text_node(cell)]}]}
                for cell in row
            ],
        })
    return {"type": "table", "attrs": {"blockId": _block_id()}, "content": body}


def math_node(latex: str) -> dict[str, Any]:
    return {"type": "blockMath", "attrs": {"blockId": _block_id(), "latex": latex[:2_000]}}


def callout(title: str, text: str, *, tone: str = "note") -> dict[str, Any]:
    return {
        "type": "callout",
        "attrs": {"blockId": _block_id(), "tone": tone, "title": title[:80]},
        "content": [{"type": "paragraph", "content": [_text_node(text)]}],
    }


def _lookup_blocks(
    snapshot: dict[str, Any], plan: dict[str, Any], unit_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    units = {unit["unit_id"]: unit for unit in plan.get("units") or []}
    unit = units.get(unit_id)
    if unit is None:
        raise CompositionError(f"生成计划中不存在知识单元 {unit_id}", code="plan_invalid")
    source = next(
        (item for item in snapshot.get("sources") or []
         if item["asset_id"] == unit["source_asset_id"]), None,
    )
    if source is None:
        raise CompositionError(f"输入快照缺少资料 {unit['source_asset_id']}", code="snapshot_invalid")
    section = next(
        (item for item in source.get("sections") or []
         if item["section_id"] == unit["section_id"]), None,
    )
    if section is None:
        raise CompositionError(f"输入快照缺少章节 {unit['section_id']}", code="snapshot_invalid")
    wanted = set(unit["block_ids"])
    blocks = [block for block in section.get("blocks") or [] if block["block_id"] in wanted]
    return unit, source, blocks


def _existing_text(snapshot: dict[str, Any], title: str) -> str:
    from app.generation.context import current_section_texts

    target = " ".join(title.split()).casefold()
    for heading, text in current_section_texts(snapshot.get("current_document") or {}).items():
        if " ".join(heading.split()).casefold() == target:
            return " ".join(text.split()).casefold()
    return ""


# ---------------------------------------------------------------------------
# Offline deterministic composer
# ---------------------------------------------------------------------------


def compose_offline(
    snapshot: dict[str, Any], plan: dict[str, Any], unit_ids: list[str],
) -> Composition:
    nodes: list[dict[str, Any]] = []
    source_map: dict[str, list[str]] = {}
    warnings: list[str] = []
    for unit_id in unit_ids:
        unit, _source, blocks = _lookup_blocks(snapshot, plan, unit_id)
        if unit.get("intent") == "skip":
            continue
        existing = _existing_text(snapshot, unit["title"])
        first_block = blocks[0]["block_id"] if blocks else None
        if unit.get("intent") != "extend" and unit.get("level", 2) <= 3:
            node = heading(unit["title"], unit.get("level") or 2)
            nodes.append(node)
            if first_block:
                source_map[node["attrs"]["blockId"]] = [first_block]
        buffer: list[str] = []
        buffer_sources: list[str] = []

        def flush(existing=existing) -> None:
            nonlocal buffer, buffer_sources
            if not buffer:
                return
            text = "\n".join(buffer).strip()
            sources = list(dict.fromkeys(buffer_sources))
            buffer, buffer_sources = [], []
            normalized = " ".join(text.split()).casefold()
            if existing and normalized and normalized in existing:
                return
            if not text:
                return
            node = paragraph(text)
            nodes.append(node)
            source_map[node["attrs"]["blockId"]] = sources

        for block in blocks:
            kind = block.get("type")
            text = (block.get("text") or "").strip()
            if kind in {"paragraph", "list_item", "caption"}:
                if len("\n".join(buffer)) + len(text) > MAX_PARAGRAPH_CHARS:
                    flush()
                buffer.append(text)
                buffer_sources.append(block["block_id"])
            elif kind == "list":
                flush()
                items = [line.strip(" -•·\t") for line in text.splitlines() if line.strip()]
                if items:
                    node = bullet_list(items)
                    nodes.append(node)
                    source_map[node["attrs"]["blockId"]] = [block["block_id"]]
            elif kind == "heading":
                flush()
                if " ".join(text.split()).casefold() == " ".join(unit["title"].split()).casefold():
                    # The section heading was already emitted for this unit.
                    continue
                # Sub-headings inside a section are kept, one level deeper.
                node = heading(text or "小节", min(int(unit.get("level") or 2) + 1, 3))
                nodes.append(node)
                source_map[node["attrs"]["blockId"]] = [block["block_id"]]
            elif kind == "equation":
                flush()
                latex = (block.get("latex") or "").strip()
                if latex:
                    node = math_node(latex)
                    nodes.append(node)
                    source_map[node["attrs"]["blockId"]] = [block["block_id"]]
                elif text:
                    buffer.append(f"公式：{text}")
                    buffer_sources.append(block["block_id"])
            elif kind == "table":
                flush()
                table = block.get("table") or {}
                rows = table.get("rows") or []
                if rows:
                    node = table_node(rows, int(table.get("header_rows") or 1))
                    nodes.append(node)
                    source_map[node["attrs"]["blockId"]] = [block["block_id"]]
                elif text:
                    buffer.append(text)
                    buffer_sources.append(block["block_id"])
            elif kind == "figure":
                flush()
                figure = block.get("figure") or {}
                description = (figure.get("description") or "").strip()
                nodes_text = "、".join(figure.get("nodes") or [])
                if description or nodes_text:
                    node = callout(
                        "图示", description or f"关键节点：{nodes_text}",
                        tone="warning" if figure.get("uncertain") else "note",
                    )
                    nodes.append(node)
                    source_map[node["attrs"]["blockId"]] = [block["block_id"]]
                else:
                    node = callout("图示待核对", "原资料包含未解读的图形，请对照原图核对。", tone="warning")
                    nodes.append(node)
                    source_map[node["attrs"]["blockId"]] = [block["block_id"]]
            elif kind == "code" and text:
                flush()
                node = {
                    "type": "codeBlock",
                    "attrs": {"blockId": _block_id()},
                    "content": [_text_node(text)],
                }
                nodes.append(node)
                source_map[node["attrs"]["blockId"]] = [block["block_id"]]
            elif text:
                if len("\n".join(buffer)) + len(text) > MAX_PARAGRAPH_CHARS:
                    flush()
                buffer.append(text)
                buffer_sources.append(block["block_id"])
        flush()
        if not blocks:
            warnings.append(f"知识单元《{unit['title']}》没有可用内容块")
    return Composition(
        nodes=nodes, source_map=source_map,
        generator="offline-extractive", generator_version="1", warnings=warnings,
    )


# ---------------------------------------------------------------------------
# DeepSeek composer
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "你是学习笔记编辑。只输出 JSON 对象："
    '{"nodes":[Tiptap节点...],"sources":{"<节点blockId>":["<原文块id>",...]}}。'
    "规则：1) 只依据给定资料陈述，不编造事实或来源；2) 每个顶层节点必须有唯一 attrs.blockId，"
    "并在 sources 中列出支撑它的原文块 id；3) 不要重写、复制已有正文，只输出需要新增的内容；"
    "4) 公式用 blockMath(latex)，表格用 table，禁止 image/URL/HTML/SVG；"
    "5) 资料不足或图形未识别时，用 callout(tone=warning) 明确写“需人工核对”，不要猜测；"
    "6) 输出应是有教学顺序的完整讲解：定义、前提、推导/方法、例题、易错点。"
)


def compose_deepseek(
    snapshot: dict[str, Any], plan: dict[str, Any], unit_ids: list[str],
) -> Composition:
    client = DeepSeekClient()
    if not client.configured:
        raise CompositionError(
            "DEEPSEEK_API_KEY 未配置，无法调用模型生成正文；可改用离线结构化生成器",
            code="model_not_configured",
        )
    payload_units = []
    allowed_ids: set[str] = set()
    for unit_id in unit_ids:
        unit, _source, blocks = _lookup_blocks(snapshot, plan, unit_id)
        if unit.get("intent") == "skip":
            continue
        payload_units.append({
            "unit_id": unit["unit_id"],
            "title": unit["title"],
            "intent": unit.get("intent"),
            "level": unit.get("level"),
            "pages": f"{unit.get('page_start')}-{unit.get('page_end')}",
            "blocks": blocks,
        })
        allowed_ids.update(block["block_id"] for block in blocks)
    if not payload_units:
        return Composition(nodes=[], source_map={}, generator="deepseek", generator_version="2")
    user_payload = {
        "notebook_title": snapshot.get("notebook_title"),
        "existing_outline": [
            item["heading"] for item in snapshot.get("current_outline") or []
        ],
        "units": payload_units,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    try:
        result = client.complete_json(messages, max_tokens=8_000)
    except DeepSeekError as exc:
        raise CompositionError(f"模型生成失败：{exc}", code="model_failed") from exc
    nodes = result.get("nodes") or result.get("blocks") or []
    sources = result.get("sources") or {}
    if not isinstance(nodes, list) or not nodes:
        raise CompositionError("模型没有返回可追加的正文节点", code="empty_generation")
    if not isinstance(sources, dict):
        raise CompositionError("模型输出缺少 sources 来源映射", code="missing_sources")
    cleaned: list[dict[str, Any]] = []
    source_map: dict[str, list[str]] = {}
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        block_id = attrs.get("blockId")
        if not isinstance(block_id, str) or not block_id.strip() or block_id in seen:
            block_id = _block_id()
            attrs["blockId"] = block_id
            node["attrs"] = attrs
        seen.add(block_id)
        ids = sources.get(block_id) or sources.get(attrs.get("blockId"))
        if not isinstance(ids, list) or not ids:
            raise CompositionError(
                f"模型输出节点 {block_id} 没有来源映射；已拒绝写入，避免无法追溯",
                code="missing_sources",
            )
        invalid = [item for item in ids if item not in allowed_ids]
        if invalid:
            raise CompositionError(
                f"模型输出引用了不存在的原文块：{invalid[:3]}", code="invalid_sources",
            )
        source_map[block_id] = list(dict.fromkeys(str(item) for item in ids))
        cleaned.append(node)
    if not cleaned:
        raise CompositionError("模型返回的节点均不可用", code="empty_generation")
    return Composition(
        nodes=cleaned, source_map=source_map, generator="deepseek", generator_version="2",
    )
