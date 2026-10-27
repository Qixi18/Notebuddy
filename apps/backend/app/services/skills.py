"""答疑技能服务：复习提纲与易混概念对比（WorkBuddy 式技能卡的后端）。

与自测卷（services/quiz.py）同一条链路模式：素材收敛 → 模型结构化 JSON →
schema 硬门槛（带原因 critique 重试）→ suggestion 回前端卡片。与 quiz 的
差异：这两类产出是纯展示物，没有判分与作答状态，因此不落库，负载直接
内嵌在 suggestion 里，前端卡片渲染即用。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.models import Material, MaterialPage, Note

SKILL_RETRIES = 2
SKILL_SOURCE_MAX_CHARS = 9000
OUTLINE_MAX_MODULES = 8
CONTRAST_MAX_PAIRS = 4


class SkillSchemaError(ValueError):
    """模型产出不符合 schema——硬门槛不通过。"""


def _skill_source(db: Session, *, course_id: str, material_id: str | None, note_id: str | None) -> str:
    """技能素材：指定笔记 > 指定课件 > 全课程笔记，截断到统一上限。"""
    if note_id:
        note = db.get(Note, note_id)
        if note is not None and note.course_id == course_id:
            return (note.content_markdown or "")[:SKILL_SOURCE_MAX_CHARS]
        return ""
    if material_id:
        material = db.get(Material, material_id)
        if material is None or material.course_id != course_id or material.deleted_at is not None:
            return ""
        pages = list(db.scalars(
            select(MaterialPage)
            .where(MaterialPage.material_id == material_id, MaterialPage.parse_status == "parsed")
            .order_by(MaterialPage.page_number)
            .limit(12)
        ).all())
        parts: list[str] = []
        used = 0
        for page in pages:
            text = f"【第 {page.page_number} 页】{page.raw_text or ''}".strip()
            if used + len(text) > SKILL_SOURCE_MAX_CHARS:
                break
            parts.append(text)
            used += len(text)
        return "\n\n".join(parts)
    notes = list(db.scalars(
        select(Note)
        .where(Note.course_id == course_id)
        .order_by(Note.material_id, Note.section_order)
        .limit(40)
    ).all())
    parts = []
    used = 0
    for note in notes:
        text = f"【{note.title}】{(note.content_markdown or '')[:600]}".strip()
        if used + len(text) > SKILL_SOURCE_MAX_CHARS:
            break
        parts.append(text)
        used += len(text)
    return "\n\n".join(parts)


def validate_outline_payload(payload: Any) -> dict[str, Any]:
    """复习提纲硬门槛：模块数、每条要点、优先级枚举都必须合规。"""
    if not isinstance(payload, dict):
        raise SkillSchemaError("顶层不是对象")
    modules = payload.get("modules")
    if not isinstance(modules, list) or not 2 <= len(modules) <= OUTLINE_MAX_MODULES:
        raise SkillSchemaError(f"modules 应为 2-{OUTLINE_MAX_MODULES} 个，实际 {len(modules) if isinstance(modules, list) else '缺失'}")
    clean: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            raise SkillSchemaError(f"第 {index} 个模块不是对象")
        title = str(module.get("title") or "").strip()
        if not title:
            raise SkillSchemaError(f"第 {index} 个模块标题为空")
        if title in seen_titles:
            raise SkillSchemaError(f"第 {index} 个模块标题与前面重复")
        seen_titles.add(title)
        items = module.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise SkillSchemaError(f"模块「{title}」要点应为 1-8 条")
        clean_items: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                raise SkillSchemaError(f"模块「{title}」存在非对象要点")
            point = str(item.get("point") or "").strip()
            if not point:
                raise SkillSchemaError(f"模块「{title}」存在空要点")
            clean_items.append({"point": point[:200], "ref": str(item.get("ref") or "").strip()[:60]})
        priority = str(module.get("priority") or "medium").strip()
        if priority not in ("high", "medium", "low"):
            priority = "medium"
        clean.append({"title": title[:80], "priority": priority, "items": clean_items})
    title = str(payload.get("title") or "复习提纲").strip()[:80] or "复习提纲"
    return {"title": title, "modules": clean}


def validate_contrast_payload(payload: Any) -> dict[str, Any]:
    """易混概念硬门槛：概念对、对比维度、名称互异都必须合规。"""
    if not isinstance(payload, dict):
        raise SkillSchemaError("顶层不是对象")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= CONTRAST_MAX_PAIRS:
        raise SkillSchemaError(f"pairs 应为 1-{CONTRAST_MAX_PAIRS} 组，实际 {len(pairs) if isinstance(pairs, list) else '缺失'}")
    clean: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            raise SkillSchemaError(f"第 {index} 组不是对象")
        name_a = str(pair.get("a") or "").strip()
        name_b = str(pair.get("b") or "").strip()
        if not name_a or not name_b:
            raise SkillSchemaError(f"第 {index} 组概念名为空")
        if name_a == name_b:
            raise SkillSchemaError(f"第 {index} 组两个概念相同")
        key = tuple(sorted((name_a, name_b)))
        if key in seen_pairs:
            raise SkillSchemaError(f"第 {index} 组与前面重复")
        seen_pairs.add(key)
        core = str(pair.get("core") or "").strip()
        if not core:
            raise SkillSchemaError(f"「{name_a} vs {name_b}」缺少一句话核心区别")
        dimensions = pair.get("dimensions")
        if not isinstance(dimensions, list) or not 2 <= len(dimensions) <= 5:
            raise SkillSchemaError(f"「{name_a} vs {name_b}」对比维度应为 2-5 个")
        clean_dims: list[dict[str, str]] = []
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                raise SkillSchemaError(f"「{name_a} vs {name_b}」存在非对象维度")
            dim_name = str(dimension.get("name") or "").strip()
            if not dim_name:
                raise SkillSchemaError(f"「{name_a} vs {name_b}」存在无名维度")
            clean_dims.append({
                "name": dim_name[:30],
                "a": str(dimension.get("a") or "").strip()[:120],
                "b": str(dimension.get("b") or "").strip()[:120],
            })
        clean.append({
            "a": name_a[:40], "b": name_b[:40], "core": core[:200],
            "dimensions": clean_dims, "anchor": str(pair.get("anchor") or "").strip()[:120],
        })
    return {"pairs": clean}


def _complete_validated(
    *, system: str, user: str, validate: Callable[[Any], Any], max_tokens: int
) -> Any:
    """调模型产出 JSON 并过硬门；不合格把具体原因喂回去重试（critique 轮）。"""
    client = DeepSeekClient()
    if not client.configured:
        raise DeepSeekError("AI 模型未配置")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: SkillSchemaError | None = None
    for _attempt in range(1, SKILL_RETRIES + 1):
        payload = client.complete_json(messages, max_tokens=max_tokens)
        try:
            return validate(payload)
        except SkillSchemaError as exc:
            last_error = exc
            messages = messages + [
                {"role": "user", "content": f"你上一次的输出未通过校验：{exc}。请修正后重新输出完整 JSON。"},
            ]
    raise last_error or SkillSchemaError("产出未通过校验")


OUTLINE_SYSTEM = """你是课程复习提纲整理器。根据给定的课程材料整理复习提纲，输出严格 JSON：
{"title": "提纲标题（≤40字）", "modules": [{"title": "模块名（≤20字）", "priority": "high|medium|low", "items": [{"point": "复习要点一句话", "ref": "来源，如「第 3 页」或笔记标题"}]}]}

硬性要求：
1. 2-6 个模块，按复习顺序排列；每模块 1-8 条要点。
2. priority 标注该模块的复习优先级：材料中反复强调、占篇幅大的设为 high。
3. 要点只来自材料内容，ref 标注来源页码或笔记标题；材料里没有的不要编。
4. 只输出 JSON，不要围栏和解释。""".strip()


def generate_review_outline_payload(source: str, *, course_name: str, focus: str) -> dict[str, Any]:
    """整理复习提纲并过硬门；不合格带原因重试，仍不合格抛 SkillSchemaError。"""
    user = f"课程：{course_name}\n{f'提纲重点：{focus}' if focus else ''}\n\n课程材料：\n---\n{source}\n---\n\n请整理复习提纲。"
    return _complete_validated(
        system=OUTLINE_SYSTEM, user=user, validate=validate_outline_payload, max_tokens=2600,
    )


CONTRAST_SYSTEM = """你是概念辨析器。根据给定的课程材料找出容易混淆的概念对，输出严格 JSON：
{"pairs": [{"a": "概念A", "b": "概念B", "core": "一句话说清核心区别", "dimensions": [{"name": "维度名（如定义/适用场景/典型错误）", "a": "A 在该维度的表现", "b": "B 在该维度的表现"}], "anchor": "一句记忆锚点"}]}

硬性要求：
1. 1-3 组概念对，选材料中真正容易混淆的；同一组内两个概念必须不同。
2. 每组 2-5 个对比维度；core 用一句话点破本质差异，不要复述维度。
3. 只辨析材料里有依据的概念，不要引入材料外的概念对。
4. 只输出 JSON，不要围栏和解释。""".strip()


def generate_concept_contrast_payload(source: str, *, course_name: str, focus: str) -> dict[str, Any]:
    """辨析易混概念并过硬门；不合格带原因重试，仍不合格抛 SkillSchemaError。"""
    user = f"课程：{course_name}\n{f'辨析重点：{focus}' if focus else ''}\n\n课程材料：\n---\n{source}\n---\n\n请找出易混概念并对比。"
    return _complete_validated(
        system=CONTRAST_SYSTEM, user=user, validate=validate_contrast_payload, max_tokens=2600,
    )
