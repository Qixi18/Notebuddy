"""Read-only course, note, forest, coverage, and term agent tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.agent_tool_types import AgentScope, ToolOutcome
from app.db.models import Course, Material, MaterialPage, Note, PageBlock
from app.forest.service import visible_note_predicate
from app.retrieval.rerank import rerank
from app.retrieval.service import RetrievedChunk, retrieve
from app.services.coverage import material_coverage

TOOL_RESULT_MAX_CHARS = 1600
CHUNK_TEXT_MAX_CHARS = 400
COVERAGE_PREVIEW_LIMIT = 8
LIST_RESULT_MAX_CHARS = 6000


def truncate(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n（内容过长，已截断）"


def load_note(db: Session, course_id: str, note_id: str) -> tuple[Note | None, str]:
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
        truncate(f"共 {len(chunks)} 条片段（按相关性排序）：\n\n{body}"),
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
    note, error = load_note(db, course_id, note_id)
    if note is None:
        return ToolOutcome("读取失败", error)
    location = f"（{note.section_key}）" if note.section_key else ""
    body = f"笔记《{note.title}》{location} 修订号 {note.revision_number}：\n\n{note.content_markdown}"
    return ToolOutcome(f"阅读笔记《{note.title}》", truncate(body))


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
    return ToolOutcome(f"跨课程搜索「{term}」命中 {len(rows)} 条", truncate("\n".join(lines)))


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
    return ToolOutcome(summary, truncate(payload))


def _explain_term(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    term = str(arguments.get("term") or "").strip()[:200]
    if not term:
        return ToolOutcome("术语为空", "请提供非空 term。")
    from app.schemas.terms import TermExplanationRequest
    from app.services.terms import explain_term_from_course

    response = explain_term_from_course(db, course_id=course_id, payload=TermExplanationRequest(term=term))
    if not response.sources:
        return ToolOutcome(f"课件未出现「{term}」", f"课程课件原文中没有出现「{term}」，请勿编造出处。")
    lines = [f"「{term}」在课程原文中的出处："]
    lines.extend(
        f"- [{source.lecture_title} | 第 {source.page_number} 页] {source.snippet[:300]}"
        for source in response.sources
    )
    return ToolOutcome(f"定位术语「{term}」的课件原文", truncate("\n".join(lines)))


def _list_course_materials(db: Session, *, course_id: str) -> ToolOutcome:
    """列出课程全部已完成课件（v6 P8）：agent 由此获得可检索的讲次清单，自主规划收窄。"""
    rows = db.execute(
        select(Material.id, Material.lecture_title, Material.page_count)
        .where(
            Material.course_id == course_id,
            Material.deleted_at.is_(None),
            Material.status == "completed",
        )
        .order_by(Material.created_at)
    ).all()
    if not rows:
        return ToolOutcome("课程暂无课件", "这门课还没有解析完成的课件。")
    lines = [f"- {material_id} 《{title}》（{page_count or 0} 页）" for material_id, title, page_count in rows]
    return ToolOutcome(f"列出课程课件 {len(rows)} 份", truncate("\n".join(lines), LIST_RESULT_MAX_CHARS))


def _read_material_page(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    """读某份课件某页的完整原文（v6 P8）：检索片段是截断的，用户问「第 N 页写了什么」时用。"""
    material_id = str(arguments.get("material_id") or "")
    material = db.get(Material, material_id) if material_id else None
    if material is None or material.course_id != course_id or material.deleted_at is not None:
        return ToolOutcome("课件不属于当前课程", "指定的 material_id 不属于当前课程。")
    try:
        page_number = int(arguments.get("page_number"))
    except (TypeError, ValueError):
        return ToolOutcome("页码无效", "请提供整数 page_number。")
    page = db.scalar(
        select(MaterialPage).where(MaterialPage.material_id == material_id, MaterialPage.page_number == page_number)
    )
    if page is None:
        total = material.page_count or 0
        return ToolOutcome(
            f"《{material.lecture_title}》没有第 {page_number} 页",
            f"该课件共 {total} 页；可用 list_course_materials 确认讲次，或改用 search_course 检索内容。",
        )
    blocks = list(db.scalars(
        select(PageBlock).where(PageBlock.page_id == page.id).order_by(PageBlock.position)
    ).all())
    body = "\n".join(block.content for block in blocks if block.content.strip()) or page.raw_text or "（本页没有可读文本）"
    return ToolOutcome(
        f"读取《{material.lecture_title}》第 {page_number} 页",
        truncate(f"[课程资料：{material.lecture_title} | 第 {page_number} 页]\n{body}"),
    )
