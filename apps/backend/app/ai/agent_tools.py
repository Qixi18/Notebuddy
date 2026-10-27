"""Agent 工具层：把现有只读服务与「建议-确认」写入包装为模型可调用的工具。

安全边界（与 ``docs/superpowers/specs/2026-10-18-agent-dock-plan.md`` 一致）：
- 只读工具直接执行，但全部校验课程归属；``note`` 作用范围下只能读锁定的笔记；
- 写工具只创建 pending 建议/提案，绝不直接修改用户正文；可编辑目标仅限
  ``editable_note_id``（锁定笔记或当前打开的笔记），跨笔记只能文字提示；
- 工具回填文本一律截断，防止多轮循环撑爆上下文。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai.agent_read_tools import (
    _explain_term,
    _get_note_coverage,
    _list_course_materials,
    _list_course_notes,
    _read_material_page,
    _read_note,
    _search_course,
    _search_forest,
    load_note,
    truncate,
)
from app.ai.agent_tool_types import AgentScope, ToolOutcome
from app.ai.note_edits import apply_note_edits
from app.db.model_utils import new_id
from app.db.models import Course
from app.knowledge.proposals import create_knowledge_proposal, create_note_suggestion
from app.services.quiz import QuizSchemaError
from app.services.skills import SkillSchemaError

NOTE_SUGGESTION_MAX_CHARS = 20000
_MAX_EDITS = 8
CHAT_MARKERS = (
    "已经提交", "待确认状态", "点「采纳」", "点「忽略」",
    "这版删了什么", "这版做了什么", "留下了什么", "我这边不会直接改动",
)


def _spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def build_tool_specs(
    *,
    scope: AgentScope,
    editable_note: bool,
    allow_web: bool = True,
    material_id: str | None = None,
    allow_note_discovery: bool = False,
    allow_quiz: bool = False,
) -> list[dict]:
    """按作用范围装配工具集：``note`` 只保留聚焦工具，``global`` 才解锁跨课程检索。

    传入 ``material_id`` 表示用户已把检索收窄到某一份课件：``search_course`` 的
    说明改为「已固定」，且不再挂 ``get_note_coverage``（覆盖率口径与「只看这讲」冲突）。
    """
    search_course_desc = (
        "在当前课程的课件（PPT/PDF/DOCX 解析块）中检索相关片段。回答需要课件依据时先调用它。"
        if not material_id
        else "在用户指定的课件（本会话已固定，无需也不允许再选其他课件）中检索相关片段。回答需要课件依据时调用它。"
    )
    specs: list[dict] = [
        _spec(
            "search_course",
            search_course_desc,
            {"query": {"type": "string", "description": "检索关键词或短语"}, "material_id": {"type": "string", "description": "可选：限定某份课件"}},
            ["query"],
        ),
        _spec(
            "read_note",
            "读取一篇课程笔记的完整 Markdown 正文。学习笔记内容、检查用户写的内容时使用。",
            {"note_id": {"type": "string", "description": "笔记 ID；锁定当前笔记时省略即读该笔记"}},
            [],
        ),
        _spec("explain_term", "在课程课件原文中定位一个术语出现的原文摘录（用于解释概念时给出课程语境）。", {"term": {"type": "string", "description": "术语"}}, ["term"]),
    ]
    # 展示型技能与笔记修改的边界：整理/提纲/对比/出题类请求走技能工具，禁止用写笔记来承载
    _skill_boundary = (
        "注意：「复习提纲/易混概念对比/出题」等展示型技能请求必须交给对应技能工具"
        "（generate_review_outline / generate_concept_contrast / generate_quiz），"
        "不要用笔记修改来承载这类产出。"
    )
    if allow_web:
        specs.append(_spec(
            "web_search",
            "联网搜索课程外部的补充资料。课件依据不足时使用；结果必须标注为网络来源，不得伪装成课程资料。",
            {"query": {"type": "string", "description": "搜索关键词"}}, ["query"],
        ))
    if scope in ("course", "global"):
        specs.append(_spec("list_course_notes", "列出当前课程全部笔记的标题与 ID，用于定位要读的笔记。", {}, []))
        specs.append(_spec(
            "list_course_materials",
            "列出当前课程全部已完成课件（ID、讲次、页数）。需要知道这门课有哪些讲、或准备收窄到某份课件/读取某页原文时先调用它。",
            {}, [],
        ))
        specs.append(_spec(
            "read_material_page",
            "读取某份课件某一页的完整原文。检索片段是截断的，需要整页原文（如用户直接问第 N 页内容）时使用；课件与页码可先用 list_course_materials 确认。",
            {
                "material_id": {"type": "string", "description": "课件 ID"},
                "page_number": {"type": "integer", "description": "页码（从 1 开始）"},
            },
            ["material_id", "page_number"],
        ))
        if not material_id:
            specs.append(_spec(
                "get_note_coverage",
                "查询某份课件的逐页收录覆盖情况（哪些页已有笔记引用、哪些页待核对）。用户问覆盖/遗漏时使用。",
                {"material_id": {"type": "string", "description": "课件 ID"}}, ["material_id"],
            ))
    if scope == "global" and not material_id:
        # material 收窄只允许在 course 档（schema 层 422 拦掉 global+material），
        # 这里不挂 search_forest 只是兜底：跨课程工具与「只看这讲」永远不该共存。
        specs.append(_spec(
            "search_forest",
            "跨全部课程搜索笔记（知识森林全局检索）。问题可能与其他课程相关时使用；结果会标明所属课程。",
            {"query": {"type": "string", "description": "课程名或知识点关键词"}}, ["query"],
        ))
    # P4 发现模式：开关开且 scope 为 course/global 时，即使没有打开的笔记，
    # 也注册 propose_note_edits（模型必须先定位再带 note_id 提交）。开关关时行为与旧版逐字节一致。
    discovery_mode = allow_note_discovery and scope in ("course", "global")
    if editable_note:
        specs.append(_spec(
            "propose_note_edits",
            "对当前打开的笔记提交结构化修改建议（pending，用户确认后才生效，不会直接改动正文）。"
            "适用场景：用户要求润色、纠错、补充或重构笔记本身。"
            + _skill_boundary +
            "不要提交整篇重写：只提交真正需要变更的操作。anchor 填笔记中某个标题的原文（不含 # 号）。",
            {
                "rationale": {"type": "string", "description": "一句话说明这批改动做什么"},
                "edits": {
                    "type": "array",
                    "description": "1-8 个操作，按笔记从头到尾的顺序给出、依次执行",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["append", "insert_after_heading", "replace_section", "remove_section"],
                                "description": "append=文末追加；insert_after_heading=在 anchor 小节末尾插入；replace_section=替换 anchor 小节正文（保留标题行）；remove_section=删除 anchor 小节（含标题与子小节）",
                            },
                            "anchor": {"type": "string", "description": "目标小节的标题原文（append 不需要）"},
                            "content": {"type": "string", "description": "Markdown 正文（remove_section 不需要；只能包含笔记本身，禁止对话文字）"},
                        },
                        "required": ["op"],
                    },
                },
            },
            ["rationale", "edits"],
        ))
        if scope in ("course", "global"):
            specs.append(_spec(
                "propose_knowledge_node",
                "提议在课程知识图谱中新增一个知识点节点（pending，用户审核后才进入图谱）。",
                {
                    "candidate_name": {"type": "string", "description": "知识点名称（≤20 字）"},
                    "candidate_summary": {"type": "string", "description": "一句话概括"},
                    "rationale": {"type": "string", "description": "提议依据"},
                    "confidence": {"type": "number", "description": "0-1 置信度"},
                },
                ["candidate_name", "candidate_summary", "rationale"],
            ))
    elif discovery_mode:
        specs.append(_spec(
            "propose_note_edits",
            "对课程内任意一篇笔记提交结构化修改建议（pending，用户确认后才生效，不会直接改动正文）。"
            "适用场景：用户明确要求修改/补充/润色某篇笔记本身。"
            + _skill_boundary +
            "必须先用 list_course_notes 或 read_note 定位目标笔记、拿到真实 note_id，再在 note_id 参数里传入；"
            "禁止凭标题猜测 ID。不要提交整篇重写：只提交真正需要变更的操作。"
            "anchor 填目标笔记中某个标题的原文（不含 # 号），不确定时先 read_note 查看结构。",
            {
                "note_id": {"type": "string", "description": "目标笔记 ID（必须先用 list_course_notes / read_note 定位获得）"},
                "rationale": {"type": "string", "description": "一句话说明这批改动做什么，并说明定位依据"},
                "edits": {
                    "type": "array",
                    "description": "1-8 个操作，按笔记从头到尾的顺序给出、依次执行",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["append", "insert_after_heading", "replace_section", "remove_section"],
                                "description": "append=文末追加；insert_after_heading=在 anchor 小节末尾插入；replace_section=替换 anchor 小节正文（保留标题行）；remove_section=删除 anchor 小节（含标题与子小节）",
                            },
                            "anchor": {"type": "string", "description": "目标小节的标题原文（append 不需要）"},
                            "content": {"type": "string", "description": "Markdown 正文（remove_section 不需要；只能包含笔记本身，禁止对话文字）"},
                        },
                        "required": ["op"],
                    },
                },
            },
            ["note_id", "rationale", "edits"],
        ))
    if allow_quiz:
        # 答疑页的技能工具族共用 allow_quiz 开关（kill switch 一并生效）：
        # 出题、复习提纲、易混概念都是「素材 → 结构化产出 → 前端技能卡」的同模式只读技能。
        # note 档也注册：锁定笔记时由执行器自动以该笔记为素材，不让「考考我」在锁笔记会话里哑火。
        specs.append(_spec(
            "generate_quiz",
            "根据课程材料出一组自测题（选择题+简答题），学生在前端作答、系统自动判分讲评。"
            "用户说「考考我/出几道题/测测我掌握得怎么样」时必须调用本工具，"
            "不要在回答文本里直接写题——那样没有作答卡和判分。"
            "用户指定某一讲时把 material_id 传给它；没指定课件时直接调用（会自动用课程笔记兜底）；"
            "锁定笔记的会话里自动针对该笔记出题，无需传 note_id。"
            "用户提到难度（如「基础题」「考考研难度」「来点挑战题」）时把原话放进 difficulty，不要自己归一化。"
            "不要在用户没要求测试时主动出题。",
            {
                "material_id": {"type": "string", "description": "可选：只针对某份课件出题"},
                "note_id": {"type": "string", "description": "可选：只针对某篇笔记出题"},
                "count": {"type": "integer", "description": "题目数量，1-5，默认 3"},
                "focus": {"type": "string", "description": "可选：出题重点（如「内聚与耦合的区别」）"},
                "difficulty": {"type": "string", "description": "可选：用户指定的难度原话（基础/进阶/挑战/考研…），用户没提就省略"},
            },
            [],
        ))
        specs.append(_spec(
            "generate_review_outline",
            "把课程内容整理成结构化复习提纲（分模块、带优先级与来源，前端渲染成可勾选进度的清单卡）。"
            "用户说「复习提纲/整理成复习提纲/帮我整理/梳理一下」时必须优先调用本工具——"
            "它是纯展示技能，产出前端卡片，不改任何笔记；不要把这类请求用 propose_note_edits 写进笔记来满足。"
            "用户指定某一讲时把 material_id 传给它。",
            {
                "material_id": {"type": "string", "description": "可选：只针对某份课件整理"},
                "note_id": {"type": "string", "description": "可选：只针对某篇笔记整理"},
                "focus": {"type": "string", "description": "可选：提纲重点"},
            },
            [],
        ))
        specs.append(_spec(
            "generate_concept_contrast",
            "从课程材料中找出易混淆的概念对，生成左右对比卡（核心区别、分维度对比、记忆锚点）。"
            "用户说「易混概念/对比说明/XX和XX有什么区别」时优先调用本工具（纯展示技能，不改笔记）。"
            "用户指定某一讲时把 material_id 传给它。",
            {
                "material_id": {"type": "string", "description": "可选：只从某份课件中找"},
                "note_id": {"type": "string", "description": "可选：只从某篇笔记中找"},
                "focus": {"type": "string", "description": "可选：指定要辨析的概念或范围"},
            },
            [],
        ))
    return specs


def _generate_quiz(db: Session, *, course_id: str, arguments: dict[str, Any], conversation_id: str | None = None, scope: AgentScope = "course", locked_note_id: str | None = None) -> ToolOutcome:
    """出自测卷（v6 P10）：素材 → 模型产出 → schema 硬门槛 → 落库 → suggestion 回前端。

    schema 不合格由服务层带具体原因重试；重试仍不合格折算为文本回模型（不中断流）。
    """
    from app.services.quiz import (
        _quiz_source,
        create_quiz,
        generate_quiz_payload,
    )

    material_id = str(arguments.get("material_id") or "") or None
    note_id = str(arguments.get("note_id") or "") or None
    if scope == "note" and locked_note_id and not note_id:
        note_id = locked_note_id  # 锁定笔记会话：素材自动落到该笔记
    try:
        count = int(arguments.get("count") or 3)
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(5, count))
    focus = str(arguments.get("focus") or "").strip()[:200]
    # 难度由用户自定义（原话保留）：不归一化成三档，避免「考研难度」被吞成「进阶」
    difficulty = str(arguments.get("difficulty") or "").strip()[:20]

    note_markdown = ""
    if note_id:
        note, error = load_note(db, course_id, note_id)
        if note is None:
            return ToolOutcome("读取笔记失败", error)
        note_markdown = note.content_markdown

    source = _quiz_source(db, course_id=course_id, material_id=material_id, note_markdown=note_markdown)
    if not source.strip():
        return ToolOutcome(
            "没有可出题的材料",
            "这门课还没有解析完成的课件，也没有指定的笔记。请先提示用户上传课程资料，或指定一篇已有笔记。",
        )
    course = db.get(Course, course_id)
    try:
        payload = generate_quiz_payload(source, count=count, focus=focus, course_name=course.name if course else "课程", difficulty=difficulty)
    except QuizSchemaError as exc:
        return ToolOutcome(
            "出题未通过校验",
            f"生成的题目未通过质量校验（{exc}）。请向用户如实说明本次出题失败，建议换个重点再试。",
        )
    except Exception as exc:  # DeepSeekError 等 → 文本降级，不断流
        return ToolOutcome(
            "出题失败",
            f"出题服务暂时不可用（{type(exc).__name__}）。请向用户说明并建议稍后再试。",
        )
    quiz = create_quiz(
        db, course_id=course_id, conversation_id=conversation_id,
        material_id=material_id, title=payload["title"], items=payload["items"],
    )
    return ToolOutcome(
        f"出了 {len(payload['items'])} 道自测题《{quiz.title}》",
        f"已创建自测卷《{quiz.title}》（{len(payload['items'])} 题，待学生作答）。"
        "请在回答里简要介绍这套题考什么，学生在前端卡片上作答后系统自动判分。",
        suggestions=[{
            "type": "quiz", "id": quiz.id, "quiz_id": quiz.id,
            "title": quiz.title, "item_count": len(payload["items"]),
        }],
    )


def _generate_review_outline(db: Session, *, course_id: str, arguments: dict[str, Any], conversation_id: str | None = None, scope: AgentScope = "course", locked_note_id: str | None = None) -> ToolOutcome:
    """整理复习提纲（技能卡）：素材 → 模型结构化 JSON → schema 硬门槛 → suggestion 回前端。

    纯展示物，不落库；schema 不合格折算文本回模型（不中断流），与 quiz 同策略。
    """
    from app.services.skills import generate_review_outline_payload

    material_id = str(arguments.get("material_id") or "") or None
    note_id = str(arguments.get("note_id") or "") or None
    if scope == "note" and locked_note_id and not note_id:
        note_id = locked_note_id  # 锁定笔记会话：素材自动落到该笔记
    focus = str(arguments.get("focus") or "").strip()[:200]

    from app.services.skills import _skill_source
    source = _skill_source(db, course_id=course_id, material_id=material_id, note_id=note_id)
    if not source.strip():
        return ToolOutcome(
            "没有可整理的材料",
            "这门课还没有可用的笔记或解析完成的课件。请先提示用户上传课程资料，或指定一篇已有笔记。",
        )
    course = db.get(Course, course_id)
    try:
        payload = generate_review_outline_payload(source, course_name=course.name if course else "课程", focus=focus)
    except SkillSchemaError as exc:
        return ToolOutcome(
            "提纲未通过校验",
            f"整理的提纲未通过质量校验（{exc}）。请向用户如实说明本次整理失败，建议换个重点再试。",
        )
    except Exception as exc:  # DeepSeekError 等 → 文本降级，不断流
        return ToolOutcome(
            "提纲整理失败",
            f"提纲服务暂时不可用（{type(exc).__name__}）。请向用户说明并建议稍后再试。",
        )
    module_count = len(payload["modules"])
    item_count = sum(len(module["items"]) for module in payload["modules"])
    from app.services.quiz import create_review_artifact

    artifact = create_review_artifact(
        db, course_id=course_id, conversation_id=conversation_id,
        kind="review_outline", title=payload["title"], payload=payload,
    )
    return ToolOutcome(
        f"整理出 {module_count} 个模块 / {item_count} 条要点的复习提纲",
        f"已生成复习提纲《{payload['title']}》（{module_count} 个模块，{item_count} 条要点，含优先级与来源）。"
        "请在回答里用一两句话介绍提纲怎么用：前端卡片上可勾选进度、按条目追问。",
        suggestions=[{
            "type": "review_outline", "id": artifact.id, "artifact_id": artifact.id,
            "favorite": False, "title": payload["title"],
            "module_count": module_count, "item_count": item_count, "modules": payload["modules"],
        }],
    )


def _generate_concept_contrast(db: Session, *, course_id: str, arguments: dict[str, Any], conversation_id: str | None = None, scope: AgentScope = "course", locked_note_id: str | None = None) -> ToolOutcome:
    """辨析易混概念（技能卡）：素材 → 结构化 JSON → 硬门槛 → suggestion 回前端。不落库。"""
    from app.services.skills import generate_concept_contrast_payload

    material_id = str(arguments.get("material_id") or "") or None
    note_id = str(arguments.get("note_id") or "") or None
    if scope == "note" and locked_note_id and not note_id:
        note_id = locked_note_id  # 锁定笔记会话：素材自动落到该笔记
    focus = str(arguments.get("focus") or "").strip()[:200]

    from app.services.skills import _skill_source
    source = _skill_source(db, course_id=course_id, material_id=material_id, note_id=note_id)
    if not source.strip():
        return ToolOutcome(
            "没有可辨析的材料",
            "这门课还没有可用的笔记或解析完成的课件。请先提示用户上传课程资料，或指定一篇已有笔记。",
        )
    course = db.get(Course, course_id)
    try:
        payload = generate_concept_contrast_payload(source, course_name=course.name if course else "课程", focus=focus)
    except SkillSchemaError as exc:
        return ToolOutcome(
            "辨析未通过校验",
            f"概念辨析未通过质量校验（{exc}）。请向用户如实说明本次辨析失败，建议换个重点再试。",
        )
    except Exception as exc:  # DeepSeekError 等 → 文本降级，不断流
        return ToolOutcome(
            "概念辨析失败",
            f"辨析服务暂时不可用（{type(exc).__name__}）。请向用户说明并建议稍后再试。",
        )
    from app.services.quiz import create_review_artifact

    pair_names = "、".join(f"「{pair['a']} vs {pair['b']}」" for pair in payload["pairs"])
    artifact = create_review_artifact(
        db, course_id=course_id, conversation_id=conversation_id,
        kind="concept_contrast", title=pair_names[:300], payload=payload,
    )
    return ToolOutcome(
        f"辨析了 {len(payload['pairs'])} 组易混概念",
        f"已生成概念辨析：{pair_names}，每组含一句话核心区别、2-5 个维度对比与记忆锚点。"
        "请在回答里点出最关键的一组区别，完整对比在前端卡片上展示；学生可就任一组继续要求出题。",
        suggestions=[{
            "type": "concept_contrast", "id": artifact.id, "artifact_id": artifact.id,
            "favorite": False, "pair_count": len(payload["pairs"]),
            "pairs": payload["pairs"],
        }],
    )


def _web_search(db: Session, *, course_id: str, arguments: dict[str, Any], allow_web: bool = True) -> ToolOutcome:
    from app.web_search.service import availability, search_policy, search_with_sources
    from app.web_search.tavily import WebSearchError

    query = str(arguments.get("query") or "").strip()[:200]
    if not query:
        return ToolOutcome("搜索词为空", "请提供非空 query。")
    policy = search_policy(allow=allow_web)
    available, reason = availability(policy)
    if not available:
        detail = f"联网搜索当前不可用（{reason or '未配置'}）。请只依据课程资料回答，并向用户说明该限制。"
        return ToolOutcome("联网补充不可用", detail)
    try:
        results = search_with_sources(
            db, course_id=course_id, query=query, policy=policy, origin="agent_tool",
        )
        if not results:
            return ToolOutcome("联网搜索无结果", "联网搜索没有返回可用结果。")
        body = "\n\n".join(
            f"[网络来源 {index + 1} | {item['title']} | {item['url']}]\n{item['snippet'][:300]}"
            for index, item in enumerate(results)
        )
        return ToolOutcome(f"联网搜索「{query}」得到 {len(results)} 条", truncate(body), web_results=results)
    except WebSearchError as exc:
        return ToolOutcome("联网搜索失败", f"联网搜索失败（{type(exc).__name__}），请只依据课程资料回答并说明限制。")


def _propose_note_edits(
    db: Session,
    *,
    course_id: str,
    editable_note_id: str | None,
    arguments: dict[str, Any],
    scope: AgentScope = "course",
    allow_note_discovery: bool = False,
) -> ToolOutcome:
    """目标笔记 = 显式 note_id 或可编辑笔记；课程护栏由 ``load_note`` 兜底。

    - note 档：目标必须是锁定的那一篇（发现开关也救不了）；
    - 发现关闭：目标必须等于打开/锁定的笔记（坞的旧行为，逐字节一致）；
    - 发现开启 + course/global：允许定位课程内任意笔记。
    """
    requested = str(arguments.get("note_id") or "").strip()
    target_id = requested or editable_note_id
    if not target_id:
        if allow_note_discovery and scope in ("course", "global"):
            return ToolOutcome(
                "未指定目标笔记",
                "请先用 list_course_notes 或 read_note 定位要修改的笔记、拿到真实 note_id，"
                "再带上它重新调用 propose_note_edits；禁止凭标题猜测 ID。",
            )
        return ToolOutcome(
            "没有可编辑的笔记",
            "当前没有锁定或打开的笔记，无法提交修改建议。请告诉用户：进入「课程笔记本」页面，"
            "在目录里点开一个具体小节（即打开笔记）后，再回到悬浮坞选择「锁定当前笔记」并重新提出修改要求。",
        )
    if target_id != editable_note_id and not (allow_note_discovery and scope in ("course", "global")):
        return ToolOutcome(
            "超出可编辑范围",
            "只能对当前打开（或锁定）的笔记提交修改建议；其他笔记请提示用户自行打开。",
        )
    note, error = load_note(db, course_id, target_id)
    if note is None:
        return ToolOutcome("读取失败", error)
    edits = arguments.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= _MAX_EDITS:
        return ToolOutcome(
            "操作列表无效",
            f"edits 必须是 1-{_MAX_EDITS} 个操作对象的数组。不要提交整篇重写：只提交真正需要变更的操作"
            "（append / insert_after_heading / replace_section / remove_section）。",
        )
    rationale = str(arguments.get("rationale") or "").strip()[:200] or "AI 学习助手提出的修改建议"
    try:
        final = apply_note_edits(note.content_markdown, edits).strip()
    except ValueError as exc:
        return ToolOutcome("操作无法执行", f"{exc}。请修正后重新提交。")
    if not final:
        return ToolOutcome("结果为空", "按这批操作修改后笔记正文为空，已拒绝；请检查是否误删全部内容。")
    if len(final) > NOTE_SUGGESTION_MAX_CHARS:
        return ToolOutcome("超出长度上限", "修改后的笔记超过长度上限，请拆分成多次较小的修改。")
    # 确定性防线 1：对话性文字混入正文（真实事故：聊天回复被整段写进笔记并逐轮累积）
    markers = [marker for marker in CHAT_MARKERS if marker in final]
    if markers:
        return ToolOutcome(
            "建议混入对话文字",
            f"修改后的正文中出现了对话性文字（{'、'.join(markers[:3])}）。操作的 content 只能包含笔记本身："
            "改动说明和解释放在你的回答正文里，不要写进 content。",
        )
    # 确定性防线 2：完全重复的段落（疑似污染底稿被再次叠加）
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", final) if paragraph.strip()]
    duplicated = {paragraph for paragraph in paragraphs if paragraphs.count(paragraph) > 1}
    if duplicated:
        return ToolOutcome(
            "建议含重复段落",
            "修改后的正文里出现了完全重复的段落。请检查操作列表：每个段落只应出现一次，不要把之前的建议内容叠加进来。",
        )
    suggestion = create_note_suggestion(
        db, note_id=note.id, proposed_markdown=final, source_ids=[], impact=rationale,
    )
    op_names = "、".join(str(edit.get("op")) for edit in edits if isinstance(edit, dict))
    return ToolOutcome(
        f"提交《{note.title}》修改建议：{len(edits)} 项操作（待用户确认）",
        f"已为笔记《{note.title}》创建结构化修改建议（{op_names}；待确认状态，不会直接改动正文）。"
        "请在回答里向用户说明每项操作的意图，由用户在前端逐块审阅后采纳。",
        suggestions=[{
            "type": "note_suggestion", "id": suggestion.id, "note_id": note.id,
            "note_title": note.title, "impact": suggestion.impact,
        }],
    )


def _propose_knowledge_node(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    name = str(arguments.get("candidate_name") or "").strip()[:300]
    summary = str(arguments.get("candidate_summary") or "").strip()[:500]
    rationale = str(arguments.get("rationale") or "").strip()[:500] or "AI 学习助手提议的新知识点"
    try:
        confidence = float(arguments.get("confidence") or 0.6)
    except (TypeError, ValueError):
        confidence = 0.6
    if not name or not summary:
        return ToolOutcome("提案字段缺失", "candidate_name 与 candidate_summary 均不能为空。")
    proposal = create_knowledge_proposal(
        db, course_id=course_id, material_id=None, candidate_name=name,
        candidate_summary=summary, kind="new", confidence=confidence,
        rationale=rationale, model_version="agent-dock-1",
    )
    return ToolOutcome(
        f"提议新知识节点《{name}》（待审核）",
        f"已创建知识图谱节点提案《{name}》（待审核状态）。请在回答里说明提议理由，由用户在知识图谱中审核。",
        suggestions=[{"type": "knowledge_proposal", "id": proposal.id, "name": proposal.candidate_name}],
    )


_EXECUTORS = {
    "search_course": _search_course,
    "read_note": _read_note,
    "list_course_notes": _list_course_notes,
    "list_course_materials": _list_course_materials,
    "read_material_page": _read_material_page,
    "search_forest": _search_forest,
    "get_note_coverage": _get_note_coverage,
    "explain_term": _explain_term,
    "web_search": _web_search,
    "generate_quiz": _generate_quiz,
    "generate_review_outline": _generate_review_outline,
    "generate_concept_contrast": _generate_concept_contrast,
    "propose_note_edits": _propose_note_edits,
    "propose_knowledge_node": _propose_knowledge_node,
}

# 工具 → 执行器关键字参数白名单：分发时按此组装，签名不匹配在代码审查期即可发现
_EXECUTOR_PARAMS: dict[str, tuple[str, ...]] = {
    "search_course": ("course_id", "arguments"),
    "read_note": ("course_id", "arguments", "scope", "locked_note_id"),
    "list_course_notes": ("course_id",),
    "list_course_materials": ("course_id",),
    "read_material_page": ("course_id", "arguments"),
    "search_forest": ("course_id", "arguments"),
    "get_note_coverage": ("course_id", "arguments"),
    "explain_term": ("course_id", "arguments"),
    "web_search": ("course_id", "arguments", "allow_web"),
    "generate_quiz": ("course_id", "arguments", "conversation_id", "scope", "locked_note_id"),
    "generate_review_outline": ("course_id", "arguments", "conversation_id", "scope", "locked_note_id"),
    "generate_concept_contrast": ("course_id", "arguments", "conversation_id", "scope", "locked_note_id"),
    "propose_note_edits": ("course_id", "arguments", "editable_note_id", "scope", "allow_note_discovery"),
    "propose_knowledge_node": ("course_id", "arguments"),
}


def execute_tool(
    db: Session,
    *,
    course_id: str,
    name: str,
    arguments: dict[str, Any],
    scope: AgentScope = "course",
    locked_note_id: str | None = None,
    editable_note_id: str | None = None,
    allow_web: bool = True,
    material_id: str | None = None,
    allow_note_discovery: bool = False,
    allow_quiz: bool = False,
    conversation_id: str | None = None,
) -> ToolOutcome:
    """执行一个工具调用；任何异常都折算成错误文本回给模型，绝不让循环中断。

    每个工具显式声明自己接收的参数（``_EXECUTOR_PARAMS``），分发时按白名单
    组装 kwargs——此前"给所有执行器统一塞 ``arguments``"的写法让不接收它的
    ``list_course_notes`` 每次调用都 TypeError。

    传入 ``material_id``（用户已收窄到某份课件）时：``search_course`` 未带
    material_id 就注入当前值；模型显式传了别的课件则直接拒绝——收窄是用户
    的显式选择，不允许模型自行扩大检索范围。
    """
    handler = _EXECUTORS.get(name)
    if handler is None:
        return ToolOutcome(f"未知工具 {name}", f"工具 {name} 不存在；可用工具见系统提示。")
    if name == "search_course" and material_id:
        requested = str(arguments.get("material_id") or "").strip()
        if requested and requested != material_id:
            return ToolOutcome(
                "超出限定课件",
                "用户已限定只关注当前课件，不能检索其他课件。请只用当前课件的内容回答，"
                "并如实说明其他资料未被纳入本次检索范围。",
            )
        if not requested:
            arguments = {**arguments, "material_id": material_id}
    available: dict[str, Any] = {
        "course_id": course_id,
        "arguments": arguments,
        "scope": scope,
        "locked_note_id": locked_note_id,
        "editable_note_id": editable_note_id,
        "allow_web": allow_web,
        "allow_note_discovery": allow_note_discovery,
        "allow_quiz": allow_quiz,
        "conversation_id": conversation_id,
    }
    kwargs = {key: available[key] for key in _EXECUTOR_PARAMS.get(name, ())}
    try:
        return handler(db, **kwargs)
    except Exception as exc:  # 工具失败必须降级为文本回给模型，不能打断 SSE 流
        return ToolOutcome(f"工具 {name} 执行失败", f"工具执行失败（{type(exc).__name__}）。请换一种方式继续，或如实告知用户该步骤失败。")


def arguments_from_json(raw: str) -> dict[str, Any]:
    """把模型给出的 arguments 字符串安全地解析成 dict；非法 JSON 返回空对象。"""
    if not raw or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
