"""Read-only agent tools over Document IR and Notebook body."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.agent_tool_types import AgentScope, ToolOutcome
from app.db.models import (
    Asset,
    Course,
    DocumentBlock,
    DocumentPage,
    Material,
    Notebook,
    NotebookBlockSource,
    NotebookSection,
)
from app.document_processing.service import current_run
from app.notes.document import document_to_markdown, load_document
from app.retrieval.rerank import rerank
from app.retrieval.service import RetrievedChunk, retrieve
from app.services.course_scope import material_in_course

TOOL_RESULT_MAX_CHARS = 1600
CHUNK_TEXT_MAX_CHARS = 400
COVERAGE_PREVIEW_LIMIT = 10
LIST_RESULT_MAX_CHARS = 6000


def truncate(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n（内容过长，已截断）"


def load_notebook(db: Session, course_id: str, notebook_id: str) -> tuple[Notebook | None, str]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        return None, "笔记不存在"
    if notebook.course_id != course_id:
        return None, "该笔记不属于当前课程，已拒绝读取"
    return notebook, ""


def _format_chunk(index: int, chunk: RetrievedChunk) -> str:
    if chunk.kind == "notebook":
        location = chunk.location_label or "当前正文"
        return f"[片段{index} | 课程笔记：{chunk.lecture_title} | {location}]\n{chunk.text[:CHUNK_TEXT_MAX_CHARS]}"
    location = chunk.location_label or (f"第 {chunk.page_number} 页" if chunk.page_number else "页码未确认")
    return f"[片段{index} | 课程资料：{chunk.lecture_title} | {location}]\n{chunk.text[:CHUNK_TEXT_MAX_CHARS]}"


def _search_course(
    db: Session, *, course_id: str, arguments: dict[str, Any],
    scope: AgentScope = "course", locked_notebook_id: str | None = None,
) -> ToolOutcome:
    query = str(arguments.get("query") or "").strip()[:200]
    if not query:
        return ToolOutcome("检索关键词为空", "请提供非空 query。")
    if scope == "note":
        notebook, error = load_notebook(db, course_id, str(locked_notebook_id or ""))
        if notebook is None:
            return ToolOutcome("笔记范围不可用", error or "当前笔记未锁定，已拒绝检索。")
        if arguments.get("material_id"):
            return ToolOutcome("超出锁定范围", "锁定笔记会话不能切换到其他课件。")
        chunks = retrieve(db, course_id=course_id, question=query, notebook_id=notebook.id, limit=6)
        if not chunks:
            return ToolOutcome(f"笔记中未检索到「{query}」", "当前锁定笔记中没有匹配片段。")
        body = "\n\n".join(_format_chunk(index + 1, chunk) for index, chunk in enumerate(chunks))
        return ToolOutcome(f"在笔记《{notebook.title}》中命中 {len(chunks)} 条", truncate(body), chunks=chunks)
    material_id = arguments.get("material_id")
    if material_id:
        material = db.get(Material, str(material_id))
        if material is None or material.deleted_at is not None or material.notebook_id is None:
            return ToolOutcome("资料不属于当前课程", "指定的 material_id 不存在或已移除。")
        notebook = db.get(Notebook, material.notebook_id)
        if notebook is None or notebook.course_id != course_id:
            return ToolOutcome("资料不属于当前课程", "指定的 material_id 不属于当前课程，已拒绝检索。")
    chunks = rerank(query, retrieve(db, course_id=course_id, question=query,
                                    material_id=material_id, limit=6))
    if not chunks:
        return ToolOutcome(
            f"检索「{query}」无命中",
            "课程资料与笔记正文中都没有检索到相关片段；如需继续请换关键词，或改用 web_search 说明是联网补充。",
        )
    body = "\n\n".join(_format_chunk(index + 1, chunk) for index, chunk in enumerate(chunks))
    return ToolOutcome(
        f"检索「{query}」命中 {len(chunks)} 条资料/正文片段",
        truncate(f"共 {len(chunks)} 条片段（按相关性排序）：\n\n{body}"),
        chunks=chunks,
    )


def _read_notebook(
    db: Session, *, course_id: str, scope: AgentScope,
    locked_notebook_id: str | None, arguments: dict[str, Any],
) -> ToolOutcome:
    requested_notebook_id = str(arguments.get("notebook_id") or "")
    if scope == "note" and requested_notebook_id and requested_notebook_id != locked_notebook_id:
        return ToolOutcome("超出锁定范围", "锁定笔记会话只能读取当前锁定的笔记。")
    notebook_id = str(locked_notebook_id if scope == "note" else requested_notebook_id or locked_notebook_id or "")
    if not notebook_id:
        return ToolOutcome(
            "未指定笔记",
            "当前没有打开或锁定的笔记。请告诉用户：打开一本课程笔记后我才能读取正文；"
            "也可以改用 search_course 检索课程资料来回答。",
        )
    notebook, error = load_notebook(db, course_id, notebook_id)
    if notebook is None:
        return ToolOutcome("读取失败", error)
    stored = load_document(notebook.document_json)
    markdown = document_to_markdown(stored.content)
    body = (
        f"笔记《{notebook.title}》revision {notebook.document_revision}：\n\n"
        f"{markdown or '（正文为空）'}"
    )
    return ToolOutcome(f"阅读笔记《{notebook.title}》", truncate(body, 8000))


def _list_course_notebooks(db: Session, *, course_id: str) -> ToolOutcome:
    rows = db.execute(
        select(Notebook, func.count(NotebookSection.id))
        .outerjoin(NotebookSection, NotebookSection.notebook_id == Notebook.id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
        .group_by(Notebook.id)
        .order_by(Notebook.display_order, Notebook.created_at)
    ).all()
    if not rows:
        return ToolOutcome("课程暂无笔记", "这门课还没有任何笔记。")
    lines = [
        f"- {notebook.id} 《{notebook.title}》revision {notebook.document_revision}（{sections} 节）"
        for notebook, sections in rows
    ]
    return ToolOutcome(f"列出课程笔记 {len(rows)} 本", truncate("\n".join(lines), LIST_RESULT_MAX_CHARS))


def _search_forest(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    term = str(arguments.get("query") or "").strip()[:200]
    if not term:
        return ToolOutcome("搜索词为空", "请提供非空 query。")
    rows = db.execute(
        select(Course.id, Course.name, Notebook.id, Notebook.title, NotebookSection.heading,
               NotebookSection.order)
        .join(Notebook, Notebook.id == NotebookSection.notebook_id)
        .join(Course, Course.id == Notebook.course_id)
        .where(
            Course.deleted_at.is_(None),
            Notebook.deleted_at.is_(None),
            or_(
                NotebookSection.heading.icontains(term, autoescape=True),
                NotebookSection.text.icontains(term, autoescape=True),
                Notebook.title.icontains(term, autoescape=True),
            ),
        )
        .order_by(Course.name, Notebook.title, NotebookSection.order)
        .limit(15)
    ).all()
    if not rows:
        return ToolOutcome(f"跨课程搜索「{term}」无命中", "所有课程笔记中都没有匹配的标题或正文。")
    lines = [
        f"- [{course_name}{'·当前课程' if row_course_id == course_id else ''}] "
        f"《{title}》第 {order + 1} 节：{heading or '（无标题）'}"
        for row_course_id, course_name, _book_id, title, heading, order in rows
    ]
    return ToolOutcome(f"跨课程搜索「{term}」命中 {len(rows)} 条", truncate("\n".join(lines)))


def _get_source_coverage(db: Session, *, course_id: str, arguments: dict[str, Any]) -> ToolOutcome:
    material_id = str(arguments.get("material_id") or "")
    material = db.get(Material, material_id) if material_id else None
    if material is None or material.deleted_at is not None or material.notebook_id is None:
        return ToolOutcome("资料不存在", "指定的 material_id 不存在或已移除。")
    notebook = db.get(Notebook, material.notebook_id)
    if notebook is None or notebook.course_id != course_id:
        return ToolOutcome("资料不属于当前课程", "指定的 material_id 不属于当前课程。")
    asset = db.get(Asset, material.asset_id) if material.asset_id else None
    run = current_run(db, asset.id) if asset is not None else None
    if run is None:
        return ToolOutcome("尚无解析版本", "这份资料还没有完成的解析版本。")
    rows = db.execute(
        select(DocumentBlock.id, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(DocumentBlock.parse_run_id == run.id, DocumentBlock.text != "")
    ).all()
    cited_ids = set(db.scalars(select(NotebookBlockSource.document_block_id).where(
        NotebookBlockSource.notebook_id == notebook.id,
        NotebookBlockSource.parse_run_id == run.id,
    )).all())
    if not rows:
        return ToolOutcome("解析无内容块", "这份解析版本没有可供引用的内容块。")
    totals: dict[int, int] = {}
    cited: dict[int, int] = {}
    for block_row_id, page in rows:
        totals[page] = totals.get(page, 0) + 1
        if block_row_id in cited_ids:
            cited[page] = cited.get(page, 0) + 1
    total = sum(totals.values())
    cited_total = sum(cited.values())
    pending = [
        f"- 第 {page} 页：{cited.get(page, 0)}/{count} 块已引用"
        for page, count in sorted(totals.items()) if cited.get(page, 0) < count
    ]
    preview = "\n".join(pending[:COVERAGE_PREVIEW_LIMIT])
    more = f"\n（其余 {len(pending) - COVERAGE_PREVIEW_LIMIT} 页略）" if len(pending) > COVERAGE_PREVIEW_LIMIT else ""
    payload = (
        f"资料《{material.lecture_title}》共 {total} 个内容块，"
        f"笔记《{notebook.title}》引用了 {cited_total} 块"
        f"（覆盖率 {round(cited_total / total * 100) if total else 0}%）。\n"
        "“已引用”指该原文块支撑了至少一个正文块，不代表整页信息全部覆盖。\n"
        f"{preview}{more}" if pending else f"资料《{material.lecture_title}》全部内容块均已有正文引用。"
    )
    return ToolOutcome(f"覆盖：{cited_total}/{total} 个内容块已引用", truncate(payload))


def _explain_term(
    db: Session, *, course_id: str, arguments: dict[str, Any],
    scope: AgentScope = "course", locked_notebook_id: str | None = None,
    fixed_material_id: str | None = None,
) -> ToolOutcome:
    term = str(arguments.get("term") or "").strip()[:200]
    if not term:
        return ToolOutcome("术语为空", "请提供非空 term。")
    notebook_id = None
    material_id = None if scope == "note" else fixed_material_id or str(arguments.get("material_id") or "").strip() or None
    if scope == "note":
        notebook, error = load_notebook(db, course_id, str(locked_notebook_id or ""))
        if notebook is None:
            return ToolOutcome("笔记范围不可用", error or "当前笔记未锁定，已拒绝检索。")
        notebook_id = notebook.id
    elif material_id:
        material = db.get(Material, material_id)
        if material is None or material.deleted_at is not None or not material_in_course(db, material, course_id):
            return ToolOutcome("资料不属于当前课程", "指定的 material_id 不存在或不属于当前课程。")
    chunks = retrieve(db, course_id=course_id, question=term, notebook_id=notebook_id,
                      material_id=material_id, limit=6)
    if not chunks:
        return ToolOutcome(f"资料未出现「{term}」", f"课程资料与笔记中没有出现「{term}」，请勿编造出处。")
    lines = [f"「{term}」在课程资料/笔记中的出处："]
    for chunk in chunks:
        if chunk.kind == "notebook":
            lines.append(f"- [课程笔记：{chunk.lecture_title} | {chunk.location_label}] {chunk.text[:300]}")
        else:
            lines.append(f"- [课程资料：{chunk.lecture_title} | 第 {chunk.page_number} 页] {chunk.text[:300]}")
    return ToolOutcome(f"定位术语「{term}」的课程原文", truncate("\n".join(lines)))


def _course_material(db: Session, course_id: str, material_id: str) -> tuple[Material | None, str]:
    material = db.get(Material, material_id) if material_id else None
    if material is None or material.deleted_at is not None:
        return None, "指定的 material_id 不存在或已移除。"
    if not material_in_course(db, material, course_id):
        return None, "指定的 material_id 不属于当前课程。"
    return material, ""


def _list_course_materials(db: Session, *, course_id: str) -> ToolOutcome:
    """列出课程课件清单：给 agent 一个可定位的 material_id 入口。"""

    rows = db.execute(
        select(Material, Notebook.title)
        .join(Notebook, Notebook.id == Material.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
               Material.deleted_at.is_(None))
        .order_by(Material.chapter_order, Material.created_at)
    ).all()
    if not rows:
        return ToolOutcome("课程暂无课件", "这门课还没有已上传的课件，无法列出讲次清单。")
    lines = [
        f"- 《{material.lecture_title}》（id={material.id}，{material.page_count or '?'} 页，状态 {material.status}）"
        for material, _notebook_title in rows
    ]
    return ToolOutcome(
        f"本课程共 {len(rows)} 份课件",
        truncate("\n".join(lines), LIST_RESULT_MAX_CHARS),
    )


def _read_material_page(
    db: Session, *, course_id: str, arguments: dict[str, Any],
    fixed_material_id: str | None = None,
) -> ToolOutcome:
    """读取课件某一页的 DocumentIR 原文（标题/公式/表格/图注）。"""

    try:
        page_number = int(arguments.get("page_number"))
    except (TypeError, ValueError):
        return ToolOutcome("页码无效", "page_number 必须是整数页码（从 1 开始）。")
    if page_number < 1:
        return ToolOutcome("页码无效", "page_number 从 1 开始。")
    material_id = fixed_material_id or str(arguments.get("material_id") or "").strip()
    material, error = _course_material(db, course_id, material_id)
    if material is None:
        return ToolOutcome("资料不可用", error)
    asset = db.get(Asset, material.asset_id) if material.asset_id else None
    run = current_run(db, asset.id) if asset is not None else None
    if run is None:
        return ToolOutcome("尚无解析版本", "这份资料还没有完成的解析版本，无法读取页面原文。")
    page = db.scalar(select(DocumentPage).where(
        DocumentPage.parse_run_id == run.id, DocumentPage.page_number == page_number,
    ))
    if page is None:
        total = db.scalar(select(func.count()).select_from(DocumentPage).where(
            DocumentPage.parse_run_id == run.id,
        )) or 0
        return ToolOutcome(
            "页码越界",
            f"《{material.lecture_title}》共 {total} 页，page_number={page_number} 不存在。",
        )
    blocks = db.scalars(select(DocumentBlock).where(
        DocumentBlock.page_id == page.id,
    ).order_by(DocumentBlock.order)).all()
    parts: list[str] = []
    for block in blocks:
        text = (block.text or "").strip()
        if block.block_type == "heading":
            if text:
                parts.append(f"【{text}】")
            continue
        latex = (block.latex or "").strip()
        if latex:
            parts.append(f"$ {latex} $")
            continue
        if block.table_json:
            parts.append(text or "（表格块）")
            continue
        if block.figure_json:
            try:
                figure = json.loads(block.figure_json)
            except (TypeError, ValueError):
                figure = {}
            description = str(figure.get("description") or "").strip() if isinstance(figure, dict) else ""
            parts.append(f"[图] {description or '图像内容未解读'}")
            continue
        if text:
            parts.append(text)
    body = (
        f"《{material.lecture_title}》第 {page_number} 页原文：\n\n" + "\n\n".join(parts)
        if parts else
        f"《{material.lecture_title}》第 {page_number} 页没有可读文本（可能是扫描页，需 OCR）。"
    )
    return ToolOutcome(f"读取《{material.lecture_title}》第 {page_number} 页", truncate(body, 8000))


__all__ = [
    "RetrievedChunk",
    "_course_material",
    "_explain_term",
    "_get_source_coverage",
    "_list_course_materials",
    "_list_course_notebooks",
    "_read_material_page",
    "_read_notebook",
    "_search_course",
    "_search_forest",
    "load_notebook",
    "truncate",
]
