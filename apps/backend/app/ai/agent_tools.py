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
    _list_course_notes,
    _read_note,
    _search_course,
    _search_forest,
    load_note,
    truncate,
)
from app.ai.agent_tool_types import AgentScope, ToolOutcome
from app.ai.note_edits import apply_note_edits
from app.knowledge.proposals import create_knowledge_proposal, create_note_suggestion

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
) -> list[dict]:
    """按作用范围装配工具集：``note`` 只保留聚焦工具，``global`` 才解锁跨课程检索。"""
    specs: list[dict] = [
        _spec(
            "search_course",
            "在当前课程的课件（PPT/PDF/DOCX 解析块）中检索相关片段。回答需要课件依据时先调用它。",
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
    if allow_web:
        specs.append(_spec(
            "web_search",
            "联网搜索课程外部的补充资料。课件依据不足时使用；结果必须标注为网络来源，不得伪装成课程资料。",
            {"query": {"type": "string", "description": "搜索关键词"}}, ["query"],
        ))
    if scope in ("course", "global"):
        specs.extend([
            _spec("list_course_notes", "列出当前课程全部笔记的标题与 ID，用于定位要读的笔记。", {}, []),
            _spec(
                "get_note_coverage",
                "查询某份课件的逐页收录覆盖情况（哪些页已有笔记引用、哪些页待核对）。用户问覆盖/遗漏时使用。",
                {"material_id": {"type": "string", "description": "课件 ID"}}, ["material_id"],
            ),
        ])
    if scope == "global":
        specs.append(_spec(
            "search_forest",
            "跨全部课程搜索笔记（知识森林全局检索）。问题可能与其他课程相关时使用；结果会标明所属课程。",
            {"query": {"type": "string", "description": "课程名或知识点关键词"}}, ["query"],
        ))
    if editable_note:
        specs.append(_spec(
            "propose_note_edits",
            "对当前打开的笔记提交结构化修改建议（pending，用户确认后才生效，不会直接改动正文）。"
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
    return specs


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
) -> ToolOutcome:
    if not editable_note_id:
        return ToolOutcome(
            "没有可编辑的笔记",
            "当前没有锁定或打开的笔记，无法提交修改建议。请告诉用户：进入「课程笔记本」页面，"
            "在目录里点开一个具体小节（即打开笔记）后，再回到悬浮坞选择「锁定当前笔记」并重新提出修改要求。",
        )
    if str(arguments.get("note_id") or editable_note_id) != editable_note_id:
        return ToolOutcome("超出可编辑范围", "只能对当前打开（或锁定）的笔记提交修改建议；其他笔记请提示用户自行打开。")
    note, error = load_note(db, course_id, editable_note_id)
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
    "search_forest": _search_forest,
    "get_note_coverage": _get_note_coverage,
    "explain_term": _explain_term,
    "web_search": _web_search,
    "propose_note_edits": _propose_note_edits,
    "propose_knowledge_node": _propose_knowledge_node,
}

# 工具 → 执行器关键字参数白名单：分发时按此组装，签名不匹配在代码审查期即可发现
_EXECUTOR_PARAMS: dict[str, tuple[str, ...]] = {
    "search_course": ("course_id", "arguments"),
    "read_note": ("course_id", "arguments", "scope", "locked_note_id"),
    "list_course_notes": ("course_id",),
    "search_forest": ("course_id", "arguments"),
    "get_note_coverage": ("course_id", "arguments"),
    "explain_term": ("course_id", "arguments"),
    "web_search": ("course_id", "arguments", "allow_web"),
    "propose_note_edits": ("course_id", "arguments", "editable_note_id"),
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
) -> ToolOutcome:
    """执行一个工具调用；任何异常都折算成错误文本回给模型，绝不让循环中断。

    每个工具显式声明自己接收的参数（``_EXECUTOR_PARAMS``），分发时按白名单
    组装 kwargs——此前"给所有执行器统一塞 ``arguments``"的写法让不接收它的
    ``list_course_notes`` 每次调用都 TypeError。
    """
    handler = _EXECUTORS.get(name)
    if handler is None:
        return ToolOutcome(f"未知工具 {name}", f"工具 {name} 不存在；可用工具见系统提示。")
    available: dict[str, Any] = {
        "course_id": course_id,
        "arguments": arguments,
        "scope": scope,
        "locked_note_id": locked_note_id,
        "editable_note_id": editable_note_id,
        "allow_web": allow_web,
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
