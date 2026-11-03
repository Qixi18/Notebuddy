"""Notebook chapter ordering use case.

The API module is responsible for resolving the requested Notebook and HTTP
payload. This service owns optimistic concurrency, order validation, and the
transaction that applies the new chapter order.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Course, Material, Notebook
from app.notes.notebook import notebook_outline
from app.schemas.notebook import NotebookOrderUpdate


def reorder_notebook(
    db: Session,
    course_id: str,
    notebook: Notebook,
    payload: NotebookOrderUpdate,
) -> dict:
    """Atomically reorder every active chapter using the expected revision."""
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook.id,
        Notebook.order_revision == payload.expected_order_revision,
    ).values(order_revision=Notebook.order_revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "章节已变化，请刷新目录后重新排序")

    materials = db.scalars(select(Material).where(
        Material.notebook_id == notebook.id,
        Material.deleted_at.is_(None),
    )).all()
    ids = payload.material_ids
    if len(set(ids)) != len(ids) or set(ids) != {material.id for material in materials}:
        db.rollback()
        raise HTTPException(422, "顺序必须包含当前笔记本全部章节，且不得重复")

    positions = {material_id: index for index, material_id in enumerate(ids)}
    for material in materials:
        material.chapter_order = positions[material.id]

    db.commit()
    db.refresh(notebook)
    course = db.get(Course, course_id)
    return notebook_outline(db, course, notebook)
