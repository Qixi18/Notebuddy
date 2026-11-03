"""Notebook 路由共享的常量、小工具与导入。

拆分自 api/v1/notebook.py，供 notebook_routes/* 复用；不注册路由。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.models import Course, Notebook
from app.notes.notebook import default_notebook

def _cover_url(book: Notebook) -> str | None:
    return f"/api/v1/notebooks/{book.id}/cover" if book.cover_filename else None

def _summary(book: Notebook) -> dict:
    return {"id": book.id, "course_id": book.course_id, "title": book.title,
            "tree_slot": book.tree_slot, "display_order": book.display_order,
            "order_revision": book.order_revision, "is_default": book.is_default,
            "created_at": book.created_at, "updated_at": book.updated_at,
            "deleted_at": book.deleted_at,
            "cover_url": _cover_url(book)}

def ensure_notebook(db: Session, course_id: str, notebook_id: str) -> Notebook:
    ensure_course(db, course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id != course_id or book.deleted_at is not None:
        raise HTTPException(404, "该课程中的笔记本不存在")
    return book

def legacy_book(db: Session, course: Course) -> Notebook:
    book = default_notebook(db, course, create=False)
    if book is None:
        raise HTTPException(404, "此课程尚无笔记本，请先新建笔记本")
    return book
