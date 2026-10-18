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
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Course, Material, Note, WebSource
from app.forest.service import visible_note_predicate
from app.knowledge.proposals import create_knowledge_proposal, create_note_suggestion
from app.retrieval.rerank import rerank
from app.retrieval.service import RetrievedChunk, retrieve
from app.services.coverage import material_coverage

AgentScope = Literal["note", "course", "global"]

# 回填给模型的单工具结果上限；检索片段另外按条截断
TOOL_RESULT_MAX_CHARS = 1600
CHUNK_TEXT_MAX_CHARS = 400
COVERAGE_PREVIEW_LIMIT = 8
NOTE_SUGGESTION_MAX_CHARS = 20000
# 笔记清单每条都带 36 位 note_id，默认截断会让大课程只看到一半，单独放宽
LIST_RESULT_MAX_CHARS = 6000

# proposed_markdown 中不允许出现的对话性文字（agent 聊天口吻混入正文的典型特征）。
# 命中即拒绝并要求模型重写；若笔记确实需要这些字样，模型换个说法即可通过。
CHAT_MARKERS = (
    "已经提交",
    "待确认状态",
    "点「采纳」",
    "点「忽略」",
    "这版删了什么",
    "这版做了什么",
    "留下了什么",
    "我这边不会直接改动",
)


@dataclass
class ToolOutcome:
    """一次工具执行的结果。

    ``payload_text`` 回填给模型（tool 角色消息）；``summary`` 供前端执行时间线展示；
    ``chunks``/``web_results`` 供收尾时按现有 evidence 机制落库；
    ``suggestions`` 是本工具创建的待确认项（前端据此渲染动作卡片）。
    """

    summary: str
    payload_text: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    web_results: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)


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
            "propose_note_edit",
            "对当前打开的笔记提交修改建议（pending，用户确认后才生效，不会直接改动正文）。"
            "proposed_markdown 必须是整篇笔记的完整新版本：保留用户原有内容，只做用户要求的修改。",
            {
                "proposed_markdown": {"type": "string", "description": "整篇笔记的完整新 Markdown"},
                "rationale": {"type": "string", "description": "一句话说明改了什么、为什么"},
            },
            ["proposed_markdown", "rationale"],
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


def _truncate(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n（内容过长，已截断）"


def _load_note(db: Session, course_id: str, note_id: str) -> tuple[Note | None, str]:
    note = db.get(Note, note_id)
    if note is None:
        return None, "笔记不存在"
    if note.course_id != course_id:
        return None, "该笔记不属于当前课程，已拒绝读取"
    return note, ""


def _format_chunk(index: int, chunk: RetrievedChunk) -> str:
    location = chunk.location_label or f"第 {chunk.page_number} 页"
    return f"[片段{index} | 课程资料：{chunk.lecture_title} | {location}]\n{chunk.text[:CHUNK_TEXT_MAX_CHARS]}"


def _search_course(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    query = str(arguments.get("query") or "").strip()[:200]
    if not query:
        return ToolOutcome("检索关键词为空", "请提供非空 query。")
    material_id = arguments.get("material_id")
    if material_id:
        material = db.get(Material, str(material_id))
        if material is None or material.course_id != course_id or material.deleted_at is not None:
            return ToolOutcome("课件不属于当前课程", "指定的 material_id 不属于当前课程，已拒绝检索。")
    chunks = rerank(query, retrieve(db, course_id=course_id, question=query, material_id=material_id, limit=4))
    if not chunks:
        return ToolOutcome(f"检索「{query}」无命中", "课程课件中没有检索到相关片段；如需继续请换关键词，或改用 web_search 说明是联网补充。")
    body = "\n\n".join(_format_chunk(index + 1, chunk) for index, chunk in enumerate(chunks))
    return ToolOutcome(
        f"检索「{query}」命中 {len(chunks)} 条课件片段",
        _truncate(f"共 {len(chunks)} 条片段（按相关性排序）：\n\n{body}"),
        chunks=chunks,
    )


def _read_note(db: Session, *, course_id: str, scope: AgentScope, locked_note_id: str | None, arguments: dict[str, Any]) -> ToolOutcome:
    note_id = str(arguments.get("note_id") or locked_note_id or "")
    if not note_id:
        return ToolOutcome(
            "未指定笔记",
            "当前没有锁定或打开的笔记。请告诉用户：进入「课程笔记本」页面，在目录里点开一个具体小节"
            "（即打开笔记）后，悬浮坞就能锁定该笔记；也可以改用 search_course 检索课件内容来回答。",
        )
    if scope == "note" and note_id != locked_note_id:
        return ToolOutcome("超出锁定范围", "当前处于「锁定当前笔记」模式，只能读取锁定的这一篇笔记。")
    note, error = _load_note(db, course_id, note_id)
    if note is None:
        return ToolOutcome("读取失败", error)
    location = f"（{note.section_key}）" if note.section_key else ""
    body = f"笔记《{note.title}》{location} 修订号 {note.revision_number}：\n\n{note.content_markdown}"
    return ToolOutcome(f"阅读笔记《{note.title}》", _truncate(body))


def _list_course_notes(db: Session, *, course_id: str) -> ToolOutcome:
    rows = db.execute(
        select(Note.id, Note.title, Material.lecture_title)
        .outerjoin(Material, Note.material_id == Material.id)
        .where(Note.course_id == course_id)
        .order_by(Note.title)
    ).all()
    if not rows:
        return ToolOutcome("课程暂无笔记", "这门课还没有任何笔记。")
    # 每条带 36 位 note_id（模型后续 read_note 要用），大课程很容易超过默认截断，
    # 这里单独放宽到 6000 并在截断时说明还有多少条未列出
    lines = [f"- {note_id} 《{title}》{f'（{lecture}）' if lecture else ''}" for note_id, title, lecture in rows]
    body = "\n".join(lines)
    if len(body) > LIST_RESULT_MAX_CHARS:
        kept = 0
        used = 0
        for line in lines:
            used += len(line) + 1
            if used > LIST_RESULT_MAX_CHARS:
                break
            kept += 1
        body = "\n".join(lines[:kept]) + f"\n（课程笔记共 {len(rows)} 条，已列出前 {kept} 条；需要其余部分请按关键词让我再查）"
        return ToolOutcome(f"列出课程笔记前 {kept}/{len(rows)} 条", body)
    return ToolOutcome(f"列出课程笔记 {len(rows)} 条", body)


def _search_forest(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    term = str(arguments.get("query") or "").strip()[:200]
    if not term:
        return ToolOutcome("搜索词为空", "请提供非空 query。")
    rows = db.execute(
        select(Course.id.label("course_id"), Course.name.label("course_name"), Note.id.label("note_id"), Note.title, Note.material_id, Note.notebook_id)
        .join(Note, Note.course_id == Course.id)
        .where(
            Course.deleted_at.is_(None),
            visible_note_predicate(),
            or_(
                Note.title.icontains(term, autoescape=True),
                Course.name.icontains(term, autoescape=True),
            ),
        )
        .order_by(Course.name, Note.title, Note.id)
        .limit(12)
    ).all()
    if not rows:
        return ToolOutcome(f"跨课程搜索「{term}」无命中", "所有课程中都没有匹配的笔记或课程名。")
    lines = [
        f"- [{course_name}{'·当前课程' if row_course_id == course_id else ''}] 《{title}》(note_id={note_id})"
        for row_course_id, course_name, note_id, title, _material, _book in rows
    ]
    return ToolOutcome(f"跨课程搜索「{term}」命中 {len(rows)} 条", _truncate("\n".join(lines)))


def _get_note_coverage(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    material_id = str(arguments.get("material_id") or "")
    material = db.get(Material, material_id) if material_id else None
    if material is None or material.course_id != course_id or material.deleted_at is not None:
        return ToolOutcome("课件不属于当前课程", "指定的 material_id 不属于当前课程。")
    coverage = material_coverage(db, material_id)
    summary = f"覆盖：{coverage['cited_locations']}/{coverage['total_locations']} 处已收录"
    review_pages = [item for item in coverage["locations"] if item["status"] != "cited"]
    preview = "\n".join(
        f"- {item['location_label']}：待核对{f'（{item['warning']}）' if item.get('warning') else ''}"
        for item in review_pages[:COVERAGE_PREVIEW_LIMIT]
    )
    more = f"\n（其余 {len(review_pages) - COVERAGE_PREVIEW_LIMIT} 处略）" if len(review_pages) > COVERAGE_PREVIEW_LIMIT else ""
    payload = (
        f"课件《{material.lecture_title}》覆盖情况：共 {coverage['total_locations']} 处，"
        f"已收录 {coverage['cited_locations']} 处，待核对 {coverage['review_locations']} 处。\n"
        "「已收录」指该位置有笔记来源映射，不代表整页信息全部覆盖。\n"
        f"{preview}{more}" if review_pages else "全部位置均已有笔记引用。"
    )
    return ToolOutcome(summary, _truncate(payload))


def _explain_term(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    term = str(arguments.get("term") or "").strip()[:200]
    if not term:
        return ToolOutcome("术语为空", "请提供非空 term。")
    from app.api.v1.terms import explain_term
    from app.schemas.terms import TermExplanationRequest

    response = explain_term(course_id, TermExplanationRequest(term=term), db)
    if not response.sources:
        return ToolOutcome(f"课件未出现「{term}」", f"课程课件原文中没有出现「{term}」，请勿编造出处。")
    lines = [f"「{term}」在课程原文中的出处："]
    lines.extend(
        f"- [{source.lecture_title} | 第 {source.page_number} 页] {source.snippet[:300]}"
        for source in response.sources
    )
    return ToolOutcome(f"定位术语「{term}」的课件原文", _truncate("\n".join(lines)))


def _web_search(db: Session, *, course_id: str, arguments: dict[str, Any], allow_web: bool = True) -> ToolOutcome:
    from app.web_search.policy import (
        SearchPolicy,
        cache_search,
        cached_search,
        can_search,
        record_search,
    )
    from app.web_search.source_review import review_results
    from app.web_search.tavily import WebSearchError
    from app.web_search.tavily import configured as web_search_configured
    from app.web_search.tavily import search as web_search

    query = str(arguments.get("query") or "").strip()[:200]
    if not query:
        return ToolOutcome("搜索词为空", "请提供非空 query。")
    policy = SearchPolicy(allow=allow_web, max_results=4, daily_limit=30, timeout_seconds=settings.web_search_timeout_seconds)
    allowed, reason = can_search(policy)
    if not allowed or not web_search_configured():
        detail = f"联网搜索当前不可用（{reason or '未配置'}）。请只依据课程资料回答，并向用户说明该限制。"
        return ToolOutcome("联网补充不可用", detail)
    audit = None
    from app.services.provider_audit import begin_call, finish_call, provider_status_from_error

    try:
        cached = cached_search(query, max_age_seconds=policy.cache_seconds)
        if cached is not None:
            results = cached
        else:
            audit, started = begin_call(
                db, provider="tavily", operation="search", course_id=course_id,
                model="tavily-basic", request_units=1, metadata={"query_length": len(query), "origin": "agent_tool"},
            )
            record_search()
            results = [item for item in web_search(query, max_results=policy.max_results)]
            results = review_results(results)["results"]
            cache_search(query, results)
            finish_call(db, audit, started, status="success", response_units=len(results))
        for item in results:
            if db.scalar(select(WebSource.id).where(WebSource.course_id == course_id, WebSource.url == item["url"])) is None:
                db.add(WebSource(
                    course_id=course_id, material_id=None, search_query=query[:1000],
                    title=item["title"], url=item["url"], site_name=item["site_name"],
                    snippet=item["snippet"], score=item.get("score"), published_at=item.get("published_at"),
                ))
        db.flush()
        if not results:
            return ToolOutcome("联网搜索无结果", "联网搜索没有返回可用结果。")
        body = "\n\n".join(
            f"[网络来源 {index + 1} | {item['title']} | {item['url']}]\n{item['snippet'][:300]}"
            for index, item in enumerate(results)
        )
        return ToolOutcome(f"联网搜索「{query}」得到 {len(results)} 条", _truncate(body), web_results=results)
    except WebSearchError as exc:
        if audit is not None:
            finish_call(db, audit, started, status=provider_status_from_error(exc), error_type=type(exc).__name__)
        return ToolOutcome("联网搜索失败", f"联网搜索失败（{type(exc).__name__}），请只依据课程资料回答并说明限制。")


def _propose_note_edit(
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
    note, error = _load_note(db, course_id, editable_note_id)
    if note is None:
        return ToolOutcome("读取失败", error)
    proposed = str(arguments.get("proposed_markdown") or "").strip()[:NOTE_SUGGESTION_MAX_CHARS]
    if len(proposed) < 1:
        return ToolOutcome("建议内容为空", "proposed_markdown 不能为空。")
    # 确定性防线 1：对话性文字混入正文（真实事故：聊天回复被整段写进笔记并逐轮累积）
    markers = [marker for marker in CHAT_MARKERS if marker in proposed]
    if markers:
        return ToolOutcome(
            "建议混入对话文字",
            f"proposed_markdown 中出现了对话性文字（{'、'.join(markers[:3])}）。笔记正文只能包含笔记本身："
            "请重写一份干净的整篇 Markdown；改动说明和解释放在你的回答正文里，不要写进 proposed_markdown。",
        )
    # 确定性防线 2：完全重复的段落（疑似污染底稿被再次叠加）
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", proposed) if paragraph.strip()]
    duplicated = {paragraph for paragraph in paragraphs if paragraphs.count(paragraph) > 1}
    if duplicated:
        return ToolOutcome(
            "建议含重复段落",
            "proposed_markdown 里出现了完全重复的段落。请以用户当前笔记为底稿重新生成一份干净的整篇正文："
            "每个段落只出现一次，不要把之前的建议或对话内容叠加进来。",
        )
    rationale = str(arguments.get("rationale") or "").strip()[:200] or "AI 学习助手提出的修改建议"
    suggestion = create_note_suggestion(
        db, note_id=note.id, proposed_markdown=proposed, source_ids=[], impact=rationale,
    )
    return ToolOutcome(
        f"提交《{note.title}》修改建议（待用户确认）",
        f"已为笔记《{note.title}》创建修改建议（待确认状态，不会直接改动正文）。请在回答里向用户说明改动要点，由用户点「采纳」生效。",
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
    "propose_note_edit": _propose_note_edit,
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
    "propose_note_edit": ("course_id", "arguments", "editable_note_id"),
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
