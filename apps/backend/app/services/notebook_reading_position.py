"""Notebook reading-position use cases."""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Material, NotebookReadingPosition, utc_now
from app.notes.document import load_document
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_notebook


def get_reading_position(db: Session, notebook_id: str) -> NotebookReadingPosition | None:
    return db.get(NotebookReadingPosition, notebook_id)


def get_scoped_reading_position(
    db: Session, course_id: str, notebook_id: str,
) -> NotebookReadingPosition | None:
    require_notebook(db, notebook_id, course_id=course_id)
    return get_reading_position(db, notebook_id)


def update_reading_position(
    db: Session,
    notebook_id: str,
    course_id: str,
    *,
    chapter_id: str | None,
    block_id: str | None,
    mode: str,
    section_offset: float,
    expected_revision: int,
) -> NotebookReadingPosition | None:
    """Validate the target and persist it with optimistic revision control."""
    notebook = require_notebook(db, notebook_id, course_id=course_id)
    if chapter_id is not None:
        material = db.get(Material, chapter_id)
        if (material is None or material.notebook_id != notebook.id
                or material.deleted_at is not None):
            raise ApplicationError(404, "阅读章节不存在或不属于当前笔记本")
    if block_id is not None:
        stored = load_document(notebook.document_json)
        live = {
            (node.get("attrs") or {}).get("blockId")
            for node in stored.content.get("content") or []
            if isinstance(node, dict)
        }
        if block_id not in live:
            raise ApplicationError(404, "阅读位置对应的正文块不存在")

    values = {"chapter_id": chapter_id, "block_id": block_id, "mode": mode,
              "section_offset": section_offset}
    values.update(revision=expected_revision + 1, updated_at=utc_now())
    if expected_revision == 0:
        db.add(NotebookReadingPosition(notebook_id=notebook.id, **values))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ApplicationError(409, "阅读位置已变化，请刷新后重试") from exc
    else:
        result = db.execute(update(NotebookReadingPosition).where(
            NotebookReadingPosition.notebook_id == notebook.id,
            NotebookReadingPosition.revision == expected_revision,
        ).values(**values))
        if result.rowcount != 1:
            db.rollback()
            raise ApplicationError(409, "阅读位置已变化，请刷新后重试")
        db.commit()

    return db.get(NotebookReadingPosition, notebook.id)
