"""Deterministic generation plan: which knowledge units to add, extend or skip.

The plan is built before any model call and persisted with the job.  It keeps
the "new vs already covered" decision auditable instead of asking the model to
avoid duplicates on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.generation.budget import (
    TARGET_OUTPUT_TOKENS,
    UNIT_OUTPUT_OVERHEAD,
    block_output_tokens,
    unit_output_tokens,
)
from app.generation.context import _normalize, block_chars


@dataclass
class KnowledgeUnit:
    unit_id: str
    title: str
    intent: str
    source_asset_id: str
    source_name: str
    parse_run_id: str
    section_id: str
    level: int
    page_start: int
    page_end: int
    block_ids: list[str] = field(default_factory=list)
    chars: int = 0
    reason: str | None = None
    output_tokens: int = 0  # Planning-only estimate; persisted plan contract is unchanged.

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "title": self.title,
            "intent": self.intent,
            "source_asset_id": self.source_asset_id,
            "source_name": self.source_name,
            "parse_run_id": self.parse_run_id,
            "section_id": self.section_id,
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "block_ids": list(self.block_ids),
            "chars": self.chars,
            "reason": self.reason,
        }


def build_plan(snapshot: dict[str, Any]) -> dict[str, Any]:
    existing = {
        _normalize(item["heading"]): item for item in snapshot.get("current_outline") or []
        if item.get("heading")
    }
    existing_text = _existing_text(snapshot)
    consumed_runs = set(snapshot.get("consumed_parse_run_ids") or [])
    units: list[KnowledgeUnit] = []
    for source in snapshot.get("sources") or []:
        for index, section in enumerate(source.get("sections") or []):
            blocks = section.get("blocks") or []
            if not blocks:
                continue
            title = (section.get("title") or "").strip() or f"{source['name']} 第 {index + 1} 部分"
            key = _normalize(title)
            intent = "new"
            reason = None
            if source["parse_run_id"] in consumed_runs:
                intent = "skip"
                reason = "该解析版本已成功生成，不重复追加（包括历史恢复后）"
            elif key in existing:
                text = _normalize(" ".join(block.get("text") or "" for block in blocks))
                if text and text in existing_text.get(key, ""):
                    intent = "skip"
                    reason = "当前正文已包含相同章节与内容"
                else:
                    intent = "extend"
                    reason = "当前正文已有同名章节，只补充缺失内容"
            unit = KnowledgeUnit(
                unit_id=f"u{len(units) + 1}",
                title=title,
                intent=intent,
                source_asset_id=source["asset_id"],
                source_name=source["name"],
                parse_run_id=source["parse_run_id"],
                section_id=section["section_id"],
                level=max(0, min(int(section.get("level") or 2), 3)),
                page_start=int(section.get("page_start") or 1),
                page_end=int(section.get("page_end") or 1),
                block_ids=[block["block_id"] for block in blocks],
                chars=sum(block_chars(block) for block in blocks),
                reason=reason,
                output_tokens=unit_output_tokens(blocks) if snapshot.get("generator") == "deepseek" else 0,
            )
            units.extend(_split_oversized(unit, blocks, snapshot))
    batches = _batch_units(units, int(snapshot.get("batch_chars") or 18_000))
    return {
        "units": [unit.to_dict() for unit in units],
        "batches": batches,
        "skip_count": sum(1 for unit in units if unit.intent == "skip"),
        "extend_count": sum(1 for unit in units if unit.intent == "extend"),
        "new_count": sum(1 for unit in units if unit.intent == "new"),
    }


def _existing_text(snapshot: dict[str, Any]) -> dict[str, str]:
    from app.generation.context import current_section_texts

    return {
        _normalize(heading): _normalize(text)
        for heading, text in current_section_texts(snapshot.get("current_document") or {}).items()
    }


def _split_oversized(
    unit: KnowledgeUnit, blocks: list[dict[str, Any]], snapshot: dict[str, Any],
) -> list[KnowledgeUnit]:
    limit = int(snapshot.get("batch_chars") or 18_000)
    output_limit = TARGET_OUTPUT_TOKENS if snapshot.get("generator") == "deepseek" else None
    if unit.chars <= limit and (output_limit is None or unit.output_tokens <= output_limit):
        return [unit]
    parts: list[KnowledgeUnit] = []
    current: list[str] = []
    chars = 0
    tokens = UNIT_OUTPUT_OVERHEAD if output_limit else 0
    for block in blocks:
        size = block_chars(block)
        block_tokens = block_output_tokens(block) if output_limit else 0
        if current and (chars + size > limit or (output_limit and tokens + block_tokens > output_limit)):
            parts.append(_clone(unit, len(parts), current, chars, tokens))
            current, chars = [], 0
            tokens = UNIT_OUTPUT_OVERHEAD if output_limit else 0
        current.append(block["block_id"])
        chars += size
        tokens += block_tokens
    if current:
        parts.append(_clone(unit, len(parts), current, chars, tokens))
    return parts


def _clone(
    unit: KnowledgeUnit, index: int, block_ids: list[str], chars: int, output_tokens: int,
) -> KnowledgeUnit:
    return KnowledgeUnit(
        unit_id=f"{unit.unit_id}-{index + 1}",
        title=unit.title if index == 0 else f"{unit.title}（续 {index + 1}）",
        intent=unit.intent,
        source_asset_id=unit.source_asset_id,
        source_name=unit.source_name,
        parse_run_id=unit.parse_run_id,
        section_id=unit.section_id,
        level=unit.level if index == 0 else min(unit.level + 1, 3),
        page_start=unit.page_start,
        page_end=unit.page_end,
        block_ids=block_ids,
        chars=chars,
        reason=unit.reason,
        output_tokens=output_tokens,
    )


def _batch_units(units: list[KnowledgeUnit], limit: int) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    tokens = 0
    for unit in units:
        if unit.intent == "skip":
            continue
        if current and (size + unit.chars > limit or tokens + unit.output_tokens > TARGET_OUTPUT_TOKENS):
            batches.append(current)
            current, size = [], 0
            tokens = 0
        current.append(unit.unit_id)
        size += unit.chars
        tokens += unit.output_tokens
    if current:
        batches.append(current)
    return batches


def units_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {unit["unit_id"]: unit for unit in plan.get("units") or []}
