"""Notebook 路由 · reading_position。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.notebook import ReadingPositionRead, ReadingPositionUpdate
from app.services.notebook_reading_position import (
    get_scoped_reading_position,
    update_reading_position,
)

router = APIRouter()

@router.get("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead | None)
def get_position(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    return get_scoped_reading_position(db, course_id, notebook_id)

@router.put("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead)
def put_position(course_id: str, notebook_id: str, payload: ReadingPositionUpdate, db: Session = Depends(get_db)):
    return update_reading_position(
        db, notebook_id, course_id, chapter_id=payload.chapter_id,
        block_id=payload.block_id, mode=payload.mode,
        section_offset=payload.section_offset,
        expected_revision=payload.expected_revision,
    )
