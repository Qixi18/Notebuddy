"""Notebook reading-position use cases."""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Material, Notebook, NotebookReadingPosition, utc_now
from app.notes.document import load_document
from app.schemas.notebook import ReadingPositionUpdate
from app.services.errors import ApplicationError


def get_reading_position(db: Session, notebook_id: str) -> NotebookReadingPosition | None:
    return db.get(NotebookReadingPosition, notebook_id)


def update_reading_position(
    db: Session,
    notebook: Notebook,
    payload: ReadingPositionUpdate,
) -> NotebookReadingPosition | None:
    """Validate the target and persist it with optimistic revision control."""
    if payload.chapter_id is not None:
        material = db.get(Material, payload.chapter_id)
        if (material is None or material.notebook_id != notebook.id
                or material.deleted_at is not None):
            raise ApplicationError(404, "阅读章节不存在或不属于当前笔记本")
    if payload.block_id is not None:
        stored = load_document(notebook.document_json)
        live = {
            (node.get("attrs") or {}).get("blockId")
            for node in stored.content.get("content") or []
            if isinstance(node, dict)
        }
        if payload.block_id not in live:
            raise ApplicationError(404, "阅读位置对应的正文块不存在")

    values = payload.model_dump(exclude={"expected_revision"})
    values.update(revision=payload.expected_revision + 1, updated_at=utc_now())
    if payload.expected_revision == 0:
        db.add(NotebookReadingPosition(notebook_id=notebook.id, **values))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ApplicationError(409, "阅读位置已变化，请刷新后重试") from exc
    else:
        result = db.execute(update(NotebookReadingPosition).where(
            NotebookReadingPosition.notebook_id == notebook.id,
            NotebookReadingPosition.revision == payload.expected_revision,
        ).values(**values))
        if result.rowcount != 1:
            db.rollback()
            raise ApplicationError(409, "阅读位置已变化，请刷新后重试")
        db.commit()

    return db.get(NotebookReadingPosition, notebook.id)
