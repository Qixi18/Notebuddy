"""Agent 工具层：只读检索 + 「建议-确认」写入（Notebook 正文）。

安全边界：
- 只读工具全部校验课程归属（经 Notebook.course_id）；
- 写工具只创建 pending 的 Notebook 修改建议，绝不直接修改正文；
- 可编辑目标仅限当前打开的 Notebook（editable_notebook_id）；
- 工具回填文本一律截断，防止多轮循环撑爆上下文。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai.agent_read_tools import (
    _explain_term,
    _get_source_coverage,
    _list_course_notebooks,
    _read_notebook,
    _search_course,
    _search_forest,
    load_notebook,
    truncate,
)
from app.ai.agent_tool_types import AgentScope, ToolOutcome
from app.db.model_utils import new_id
from app.db.models import Notebook, NotebookEditSuggestion
from app.knowledge.proposals import create_knowledge_proposal
from app.notes.document import document_to_markdown, dump_document, load_document
from app.notes.edits import EditRejected, apply_edits, count_ops

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
    editable_notebook: bool,
    allow_web: bool = True,
) -> list[dict]:
    specs: list[dict] = [
        _spec(
            "search_course",
            "检索当前课程的资料解析内容与学习笔记正文。回答需要课程依据时先调用它。",
            {"query": {"type": "string", "description": "检索关键词或短语"},
             "material_id": {"type": "string", "description": "可选：限定某份资料"}},
            ["query"],
        ),
        _spec(
            "read_notebook",
            "读取一本课程笔记的完整正文（Markdown 视图）。检查用户写的内容时使用。",
            {"notebook_id": {"type": "string", "description": "笔记 ID；当前打开的笔记可省略"}},
            [],
        ),
        _spec("explain_term", "在课程资料与笔记中定位一个术语出现的原文摘录。",
              {"term": {"type": "string", "description": "术语"}}, ["term"]),
    ]
    if allow_web:
        specs.append(_spec(
            "web_search",
            "联网搜索课程外部的补充资料。课程依据不足时使用；结果必须标注为网络来源。",
            {"query": {"type": "string", "description": "搜索关键词"}}, ["query"],
        ))
    if scope in ("course", "global"):
        specs.extend([
            _spec("list_course_notebooks", "列出当前课程全部笔记的标题、ID 与节数。", {}, []),
            _spec(
                "get_source_coverage",
                "查询某份资料的解析内容被当前课程笔记正文引用了多少（覆盖/遗漏）。",
                {"material_id": {"type": "string", "description": "资料 ID"}}, ["material_id"],
            ),
        ])
    if scope == "global":
        specs.append(_spec(
            "search_forest",
            "跨全部课程搜索笔记正文（知识森林全局检索）。结果会标明所属课程。",
            {"query": {"type": "string", "description": "课程名、笔记标题或知识点关键词"}},
            ["query"],
        ))
    if editable_notebook:
        specs.append(_spec(
            "propose_notebook_edits",
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
    except WebSearchError:
        return ToolOutcome("联网搜索失败", "联网搜索失败，请只依据课程资料回答并说明限制。")


def _propose_notebook_edits(
    db: Session,
    *,
    course_id: str,
    editable_notebook_id: str | None,
    arguments: dict[str, Any],
) -> ToolOutcome:
    if not editable_notebook_id:
        return ToolOutcome(
            "没有可编辑的笔记",
            "当前没有打开的笔记，无法提交修改建议。请告诉用户先打开一本笔记再提问。",
        )
    if str(arguments.get("notebook_id") or editable_notebook_id) != editable_notebook_id:
        return ToolOutcome("超出可编辑范围", "只能对当前打开（或锁定）的笔记提交修改建议。")
    notebook, error = load_notebook(db, course_id, editable_notebook_id)
    if notebook is None:
        return ToolOutcome("读取失败", error)
    edits = arguments.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= _MAX_EDITS:
        return ToolOutcome(
            "操作列表无效",
            f"edits 必须是 1-{_MAX_EDITS} 个操作对象的数组。不要提交整篇重写。",
        )
    rationale = str(arguments.get("rationale") or "").strip()[:200] or "AI 学习助手提出的修改建议"
    stored = load_document(notebook.document_json)
    try:
        final = apply_edits(stored.content, edits)
    except EditRejected as exc:
        return ToolOutcome("操作无法执行", f"{exc}。请修正后重新提交。")
    markdown = document_to_markdown(final)
    if not markdown.strip():
        return ToolOutcome("结果为空", "按这批操作修改后笔记正文为空，已拒绝。")
    if len(markdown) > NOTE_SUGGESTION_MAX_CHARS:
        return ToolOutcome("超出长度上限", "修改后的笔记超过长度上限，请拆分成多次较小的修改。")
    markers = [marker for marker in CHAT_MARKERS if marker in markdown]
    if markers:
        return ToolOutcome(
            "建议混入对话文字",
            f"修改后的正文中出现了对话性文字（{'、'.join(markers[:3])}）。操作的 content 只能包含笔记本身。",
        )
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", markdown) if paragraph.strip()]
    duplicated = {paragraph for paragraph in paragraphs if paragraphs.count(paragraph) > 1}
    if duplicated:
        return ToolOutcome(
            "建议含重复段落",
            "修改后的正文里出现了完全重复的段落。请检查操作列表：每个段落只应出现一次。",
        )
    suggestion = NotebookEditSuggestion(
        id=new_id(),
        notebook_id=notebook.id,
        base_revision=notebook.document_revision,
        rationale=rationale,
        ops_json=json.dumps(edits, ensure_ascii=False),
        proposed_document_json=dump_document(final),
        status="pending",
    )
    db.add(suggestion)
    db.flush()
    return ToolOutcome(
        f"提交《{notebook.title}》修改建议：{len(edits)} 项操作（待用户确认）",
        f"已为笔记《{notebook.title}》创建结构化修改建议（{count_ops(edits)}；待确认状态，不会直接改动正文）。"
        "请在回答里向用户说明每项操作的意图，由用户在前端逐块审阅后采纳。",
        suggestions=[{
            "type": "notebook_edit_suggestion", "id": suggestion.id,
            "notebook_id": notebook.id, "notebook_title": notebook.title,
            "base_revision": suggestion.base_revision, "impact": rationale,
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
        rationale=rationale, model_version="agent-dock-2",
    )
    return ToolOutcome(
        f"提议新知识节点《{name}》（待审核）",
        f"已创建知识图谱节点提案《{name}》（待审核状态）。请在回答里说明提议理由，由用户在知识图谱中审核。",
        suggestions=[{"type": "knowledge_proposal", "id": proposal.id, "name": proposal.candidate_name}],
    )


_EXECUTORS = {
    "search_course": _search_course,
    "read_notebook": _read_notebook,
    "list_course_notebooks": _list_course_notebooks,
    "search_forest": _search_forest,
    "get_source_coverage": _get_source_coverage,
    "explain_term": _explain_term,
    "web_search": _web_search,
    "propose_notebook_edits": _propose_notebook_edits,
    "propose_knowledge_node": _propose_knowledge_node,
}

_EXECUTOR_PARAMS: dict[str, tuple[str, ...]] = {
    "search_course": ("course_id", "arguments"),
    "read_notebook": ("course_id", "arguments", "scope", "locked_notebook_id"),
    "list_course_notebooks": ("course_id",),
    "search_forest": ("course_id", "arguments"),
    "get_source_coverage": ("course_id", "arguments"),
    "explain_term": ("course_id", "arguments"),
    "web_search": ("course_id", "arguments", "allow_web"),
    "propose_notebook_edits": ("course_id", "arguments", "editable_notebook_id"),
    "propose_knowledge_node": ("course_id", "arguments"),
}


def execute_tool(
    db: Session,
    *,
    course_id: str,
    name: str,
    arguments: dict[str, Any],
    scope: AgentScope = "course",
    locked_notebook_id: str | None = None,
    editable_notebook_id: str | None = None,
    allow_web: bool = True,
) -> ToolOutcome:
    handler = _EXECUTORS.get(name)
    if handler is None:
        return ToolOutcome(f"未知工具 {name}", f"工具 {name} 不存在；可用工具见系统提示。")
    available: dict[str, Any] = {
        "course_id": course_id,
        "arguments": arguments,
        "scope": scope,
        "locked_notebook_id": locked_notebook_id,
        "editable_notebook_id": editable_notebook_id,
        "allow_web": allow_web,
    }
    kwargs = {key: available[key] for key in _EXECUTOR_PARAMS.get(name, ())}
    try:
        return handler(db, **kwargs)
    except Exception as exc:  # 工具失败必须降级为文本回给模型，不能打断 SSE 流
        return ToolOutcome(
            f"工具 {name} 执行失败",
            f"工具执行失败（{type(exc).__name__}）。请换一种方式继续，或如实告知用户该步骤失败。",
        )


def arguments_from_json(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


__all__ = ["Notebook", "arguments_from_json", "build_tool_specs", "execute_tool"]
