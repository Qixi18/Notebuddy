"""Notebook 路由共享的常量、小工具与导入。

拆分自 api/v1/notebook.py，供 notebook_routes/* 复用；不注册路由。
"""
from __future__ import annotations

from app.db.models import Notebook


def _cover_url(book: Notebook) -> str | None:
    return f"/api/v1/notebooks/{book.id}/cover" if book.cover_filename else None

def _summary(book: Notebook) -> dict:
    return {"id": book.id, "course_id": book.course_id, "title": book.title,
            "tree_slot": book.tree_slot, "display_order": book.display_order,
            "order_revision": book.order_revision, "is_default": book.is_default,
            "created_at": book.created_at, "updated_at": book.updated_at,
            "deleted_at": book.deleted_at,
            "cover_url": _cover_url(book)}
