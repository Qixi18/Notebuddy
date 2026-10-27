"""Derived Notebook section index (rebuildable).

Search, course structure and the course tree read this index instead of parsing
``document_json`` on every request.  It is rebuilt from the authoritative
document whenever the document changes; it is never an independent body.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.model_utils import new_id
from app.db.models import Notebook, NotebookSection, utc_now


@dataclass
class SectionDraft:
    block_id: str
    order: int
    level: int
    heading: str
    text: str


def node_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text") or "")
    if node_type == "hardBreak":
        return "\n"
    if node_type == "inlineMath":
        return f"${(node.get('attrs') or {}).get('latex', '')}$"
    if node_type == "blockMath":
        return f"$${(node.get('attrs') or {}).get('latex', '')}$$"
    if node_type == "image":
        return f"[图片]{(node.get('attrs') or {}).get('alt', '')}"
    if node_type == "table":
        rows = []
        for row in node.get("content") or []:
            cells = [node_text(cell).strip() for cell in row.get("content") or []]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
    separator = "\n" if node_type in {"doc", "bulletList", "orderedList", "taskList", "table"} else ""
    return separator.join(part for part in (node_text(child) for child in node.get("content") or []) if part)


def build_sections(content: dict[str, Any]) -> list[SectionDraft]:
    sections: list[SectionDraft] = []
    current: SectionDraft | None = None
    for node in content.get("content") or []:
        if not isinstance(node, dict):
            continue
        attrs = node.get("attrs") or {}
        block_id = attrs.get("blockId")
        if not isinstance(block_id, str) or not block_id:
            block_id = f"block-{len(sections)}-{len(current.text) if current else 0}"
        if node.get("type") == "heading":
            level = attrs.get("level")
            current = SectionDraft(
                block_id=block_id, order=len(sections), level=level if isinstance(level, int) else 1,
                heading=node_text(node).strip(), text="",
            )
            sections.append(current)
            continue
        if current is None:
            current = SectionDraft(block_id=block_id, order=0, level=0, heading="", text="")
            sections.append(current)
        piece = node_text(node).strip()
        if piece:
            current.text = f"{current.text}\n{piece}".strip() if current.text else piece
    return sections


def rebuild_notebook_sections(
    db: Session, notebook: Notebook, content: dict[str, Any], revision: int,
) -> int:
    db.execute(delete(NotebookSection).where(NotebookSection.notebook_id == notebook.id))
    drafts = build_sections(content)
    now = utc_now()
    for draft in drafts:
        db.add(NotebookSection(
            id=new_id(), notebook_id=notebook.id, course_id=notebook.course_id,
            block_id=draft.block_id[:64], order=draft.order, level=max(0, draft.level),
            heading=draft.heading[:500], text=draft.text, revision=revision, created_at=now,
        ))
    db.flush()
    return len(drafts)


def rebuild_notebook_index(db: Session, notebook_id: str) -> int:
    from app.notes.document import load_document

    notebook = db.get(Notebook, notebook_id)
    if notebook is None:
        return 0
    stored = load_document(notebook.document_json)
    return rebuild_notebook_sections(db, notebook, stored.content, notebook.document_revision)


def rebuild_all(db: Session, *, limit: int | None = None) -> int:
    query = select(Notebook).where(Notebook.deleted_at.is_(None))
    if limit:
        query = query.limit(limit)
    total = 0
    for notebook in db.scalars(query).all():
        total += rebuild_notebook_index(db, notebook.id)
    return total


def sections_for_notebook(db: Session, notebook_id: str) -> list[NotebookSection]:
    return list(db.scalars(select(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).order_by(NotebookSection.order)).all())


def search_sections(
    db: Session, term: str, *, course_id: str | None = None, limit: int = 40,
) -> list[NotebookSection]:
    query = select(NotebookSection).join(
        Notebook, Notebook.id == NotebookSection.notebook_id,
    ).where(
        Notebook.deleted_at.is_(None),
        (NotebookSection.heading.icontains(term, autoescape=True))
        | (NotebookSection.text.icontains(term, autoescape=True)),
    )
    if course_id:
        query = query.where(NotebookSection.course_id == course_id)
    return list(db.scalars(query.order_by(NotebookSection.notebook_id, NotebookSection.order)
                            .limit(limit)).all())


def section_payload(row: NotebookSection, notebook_title: str, course_name: str | None) -> dict:
    return {
        "notebook_id": row.notebook_id,
        "notebook_title": notebook_title,
        "course_id": row.course_id,
        "course_name": course_name,
        "block_id": row.block_id,
        "heading": row.heading,
        "text": row.text,
        "level": row.level,
        "order": row.order,
        "revision": row.revision,
    }


def store_sections_snapshot(sections: list[NotebookSection]) -> str:
    return json.dumps([
        {"block_id": row.block_id, "heading": row.heading, "order": row.order} for row in sections
    ], ensure_ascii=False)
