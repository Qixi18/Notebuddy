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
NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS = 20_000


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
            elif kind in {"figure", "image"}:
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
    "4) 数学内容必须使用数学节点：中文句子中嵌入的短公式使用 inlineMath，独占一行或需要展示的推导使用 blockMath；"
    "公式 attrs.latex 只放裸 LaTeX 字符串，不带 $、$$、\\(、\\)、\\[、\\] 定界符，不是 HTML 或图片。"
    "例如段落 content 可为 [{\"type\":\"text\",\"text\":\"设点列 \"},"
    "{\"type\":\"inlineMath\",\"attrs\":{\"latex\":\"x_k\\\\to a\"}},"
    "{\"type\":\"text\",\"text\":\" 在 \"},"
    "{\"type\":\"inlineMath\",\"attrs\":{\"latex\":\"\\\\mathbb{R}^n\"}},"
    "{\"type\":\"text\",\"text\":\" 中收敛。\"}]；不要把 x_k、R^n、(x-x_0)^2 等教学公式写成普通 text。"
    "不要给 inlineMath 添加 blockId；来源映射归属于它所在的顶层块。"
    "列表项内部是 listItem→paragraph；callout 的 content 内放 paragraph；tableCell/tableHeader 的 content 内放 paragraph。"
    "这些容器里的中文说明与短公式都拆成 text + inlineMath；独占行公式用带 blockId 的 blockMath 顶层节点。"
    "表格用 table，tableCell/tableHeader 的文本需放入 paragraph。"
    "callout 要有 title，内部内容放入 paragraph；禁止 image、URL 节点、HTML、SVG 及不可信链接/HTML 数学命令；"
    "5) 资料不足或图形未识别时，用 callout(tone=warning) 明确写“需人工核对”，不要猜测；"
    "6) 输出应是有教学顺序的完整讲解：定义、前提、推导/方法、例题、易错点。"
)

JSON_REPAIR_PROMPT = (
    "请重新生成上一请求要求的完整结果，并仅输出严格 JSON 对象，禁止 Markdown 代码围栏或解释。"
    "为确保输出完整，正文保持精炼；顶层结构必须包含 nodes 数组和 sources 对象，"
    "每个节点都必须有唯一 attrs.blockId，且 sources 必须用相同 blockId 映射到至少一个输入原文块 ID。"
)

SOURCE_REPAIR_PROMPT = (
    "只修复正文节点的来源映射，不改写节点内容，也不要新增节点。"
    "仅输出 JSON 对象 {\"sources\":{\"节点 blockId\":[\"输入原文块 ID\"]}}。"
    "只为有明确依据的节点添加映射，引用只能来自允许原文块 ID；不得猜测、勉强匹配或虚构 ID。"
    "没有来源依据的节点返回空数组，本地校验会拒绝写入。"
)

FORMAT_REPAIR_PROMPT = (
    "请只修复给定 Tiptap 正文 JSON 的结构格式，使其通过 NoteBuddy Notebook document v2 校验。"
    "不得改变知识含义、删除有效内容、添加事实或更改任何 blockId；已有 inlineMath/blockMath 的 attrs.latex 必须逐字保留，"
    "不得改动其中的变量、运算符、比较符、上下标、正负号或分组；每个顶层正文节点都必须保留原 blockId，"
    "sources 必须逐项保留并为每个节点映射至少一个允许的原文块 ID。"
    "允许的顶层类型仅为 paragraph、heading、bulletList、orderedList、taskList、blockquote、codeBlock、"
    "horizontalRule、table、callout、example、blockMath。正文结构、attrs、子节点、marks 和文本必须符合 Tiptap。"
    "只输出完整 JSON 对象 {\"nodes\":[...],\"sources\":{...}}，不要 Markdown 或解释。"
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
        result = client.complete_json(messages, max_tokens=NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS)
        json_repair_used = False
    except DeepSeekError as first_error:
        # Repair malformed/truncated JSON once while preserving the original
        # evidence payload.  A second failure remains visible to the user.
        if first_error.code != "invalid_json":
            raise CompositionError(f"模型生成失败：{first_error}", code="model_failed") from first_error
        repair_messages = [
            *messages,
            {"role": "assistant", "content": "上一次模型输出无法解析为 JSON。"},
            {"role": "user", "content": JSON_REPAIR_PROMPT},
        ]
        try:
            result = client.complete_json(
                repair_messages, max_tokens=NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS,
            )
            json_repair_used = True
        except DeepSeekError as exc:
            raise CompositionError(f"模型生成失败（JSON 修复重试后仍无效）：{exc}", code="model_failed") from exc
    try:
        return _composition_from_deepseek_result(result, allowed_ids)
    except CompositionError as exc:
        if json_repair_used or exc.code not in {"missing_sources", "invalid_sources"}:
            raise
        source_error = exc

    nodes = result.get("nodes") or result.get("blocks") or []
    if not isinstance(nodes, list):
        raise CompositionError("模型没有返回可修复的正文节点", code="empty_generation")
    # First pass assigns unique IDs to duplicate/missing model IDs. Reuse that
    # normalized list for the source-only retry so the mapping keys are stable.
    normalized_nodes, _aliases = _normalize_model_node_ids(nodes)
    repair_messages = [
        *messages,
        {"role": "assistant", "content": json.dumps({"nodes": normalized_nodes}, ensure_ascii=False)},
        {"role": "user", "content": json.dumps({
            "instruction": SOURCE_REPAIR_PROMPT,
            "allowed_source_block_ids": sorted(allowed_ids),
            "validation_error": str(source_error),
        }, ensure_ascii=False)},
    ]
    try:
        repaired = client.complete_json(
            repair_messages, max_tokens=NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS,
        )
    except DeepSeekError as exc:
        raise CompositionError(f"模型来源映射修复失败：{exc}", code="missing_sources") from exc
    repaired_sources = repaired.get("sources")
    if not isinstance(repaired_sources, dict):
        raise CompositionError("模型来源映射修复响应缺少 sources 对象", code="missing_sources")
    return _composition_from_deepseek_result(
        {"nodes": normalized_nodes, "sources": repaired_sources}, allowed_ids,
    )


def repair_deepseek_document_format(
    nodes: list[dict[str, Any]],
    source_map: dict[str, list[str]],
    allowed_source_ids: set[str],
    validation_error: str,
) -> Composition:
    """Ask the model to repair a rejected document fragment without changing its evidence."""
    client = DeepSeekClient()
    if not client.configured:
        raise CompositionError("格式矫正需要已配置的 DeepSeek 模型", code="model_not_configured")
    request = {
        "nodes": nodes,
        "sources": source_map,
        "allowed_source_block_ids": sorted(allowed_source_ids),
        "validation_error": validation_error[:1_000],
    }
    try:
        result = client.complete_json([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            {"role": "user", "content": FORMAT_REPAIR_PROMPT},
        ], max_tokens=NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS)
    except DeepSeekError as exc:
        raise CompositionError(f"模型正文格式矫正失败：{exc}", code="document_format_repair_failed") from exc
    try:
        composition = _composition_from_deepseek_result(result, allowed_source_ids)
    except CompositionError as exc:
        raise CompositionError(
            f"模型正文格式矫正结果未通过来源校验：{exc}", code="document_format_repair_failed",
        ) from exc
    if set(composition.source_map) != {
        (node.get("attrs") or {}).get("blockId") for node in composition.nodes
    }:
        raise CompositionError("格式矫正改变了正文块与来源的对应关系", code="document_format_repair_failed")
    return composition


def _normalize_model_node_ids(
    nodes: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    normalized: list[dict[str, Any]] = []
    aliases: dict[str, str | None] = {}
    seen: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        node = raw
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        original_id = attrs.get("blockId")
        block_id = original_id
        duplicate_id = isinstance(block_id, str) and block_id in seen
        if not isinstance(block_id, str) or not block_id.strip() or duplicate_id:
            block_id = _block_id()
            attrs["blockId"] = block_id
            node["attrs"] = attrs
        seen.add(block_id)
        aliases[block_id] = original_id if isinstance(original_id, str) and not duplicate_id else None
        normalized.append(node)
    return normalized, aliases


def _composition_from_deepseek_result(
    result: dict[str, Any], allowed_ids: set[str],
) -> Composition:
    nodes = result.get("nodes") or result.get("blocks") or []
    sources = result.get("sources")
    if sources is None:
        sources = {}
    if not isinstance(nodes, list) or not nodes:
        raise CompositionError("模型没有返回可追加的正文节点", code="empty_generation")
    if not isinstance(sources, dict):
        raise CompositionError("模型输出缺少 sources 来源映射", code="missing_sources")
    cleaned, source_aliases = _normalize_model_node_ids(nodes)
    source_map: dict[str, list[str]] = {}
    for node in cleaned:
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        block_id = attrs.get("blockId")
        original_id = source_aliases.get(block_id)
        ids = sources.get(original_id) if isinstance(original_id, str) else None
        ids = ids or sources.get(block_id)
        if not isinstance(ids, list) or not ids:
            raise CompositionError(
                f"模型输出节点 {block_id} 没有来源映射；已拒绝写入，避免无法追溯",
                code="missing_sources",
            )
        if not all(isinstance(item, str) and item for item in ids):
            raise CompositionError(
                f"模型输出节点 {block_id} 的来源映射格式无效", code="missing_sources",
            )
        invalid = [item for item in ids if item not in allowed_ids]
        if invalid:
            raise CompositionError(
                f"模型输出引用了不存在的原文块：{invalid[:3]}", code="invalid_sources",
            )
        source_map[block_id] = list(dict.fromkeys(ids))
    if not cleaned:
        raise CompositionError("模型返回的节点均不可用", code="empty_generation")
    return Composition(
        nodes=cleaned, source_map=source_map, generator="deepseek", generator_version="4",
    )
