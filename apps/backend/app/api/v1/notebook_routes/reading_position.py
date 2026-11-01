"""Notebook 路由 · reading_position。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Material, NotebookReadingPosition, utc_now
from app.notes.document import load_document
from app.schemas.notebook import ReadingPositionRead, ReadingPositionUpdate

from .common import (
    ensure_notebook,
)

router = APIRouter()

@router.get("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead | None)
def get_position(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return db.get(NotebookReadingPosition, notebook_id)

@router.put("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead)
def put_position(course_id: str, notebook_id: str, payload: ReadingPositionUpdate, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    if payload.chapter_id is not None:
        material = db.get(Material, payload.chapter_id)
        if (material is None or material.notebook_id != notebook_id
                or material.deleted_at is not None):
            raise HTTPException(404, "阅读章节不存在或不属于当前笔记本")
    if payload.block_id is not None:
        stored = load_document(book.document_json)
        live = {
            (node.get("attrs") or {}).get("blockId")
            for node in stored.content.get("content") or []
            if isinstance(node, dict)
        }
        if payload.block_id not in live:
            raise HTTPException(404, "阅读位置对应的正文块不存在")
    values = payload.model_dump(exclude={"expected_revision"})
    values.update(revision=payload.expected_revision + 1, updated_at=utc_now())
    if payload.expected_revision == 0:
        db.add(NotebookReadingPosition(notebook_id=notebook_id, **values))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "阅读位置已变化，请刷新后重试") from exc
    else:
        result = db.execute(update(NotebookReadingPosition).where(
            NotebookReadingPosition.notebook_id == notebook_id,
            NotebookReadingPosition.revision == payload.expected_revision).values(**values))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "阅读位置已变化，请刷新后重试")
        db.commit()
    return db.get(NotebookReadingPosition, notebook_id)
