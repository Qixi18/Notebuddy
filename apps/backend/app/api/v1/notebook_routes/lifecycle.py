"""Notebook 路由 · lifecycle。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Course,
    Notebook,
)
from app.notes.notebook import list_course_notebooks, notebook_outline
from app.schemas.notebook import (
    NotebookBindRequest,
    NotebookBulkManageRequest,
    NotebookMoveRequest,
    NotebookOrderUpdate,
    NotebookRead,
    NotebookRestoreDeletedRequest,
    NotebookSummary,
    NotebookTitleUpdate,
    UnboundNotebookSummary,
)
from app.services.deletion import DeletionConflict, permanently_delete_notebook
from app.services.notebook_lifecycle import (
    bind_notebook as bind_notebook_service,
)
from app.services.notebook_lifecycle import (
    bulk_manage_notebooks as bulk_manage_notebooks_service,
)
from app.services.notebook_lifecycle import (
    create_course_notebook as create_course_notebook_service,
)
from app.services.notebook_lifecycle import (
    create_unbound_notebook as create_unbound_notebook_service,
)
from app.services.notebook_lifecycle import (
    delete_course_notebook as delete_course_notebook_service,
)
from app.services.notebook_lifecycle import (
    delete_unbound_notebook as delete_unbound_notebook_service,
)
from app.services.notebook_lifecycle import (
    move_notebook as move_notebook_service,
)
from app.services.notebook_lifecycle import (
    rename_notebook as rename_notebook_service,
)
from app.services.notebook_lifecycle import (
    restore_deleted_notebook as restore_deleted_notebook_service,
)
from app.services.notebook_lifecycle import (
    unbind_notebook as unbind_notebook_service,
)
from app.services.notebook_order import reorder_notebook as reorder_notebook_service

from .common import (
    _summary,
    ensure_notebook,
    legacy_book,
)

router = APIRouter()

@router.post("/notebooks/bulk-manage")
def bulk_manage_notebooks(payload: NotebookBulkManageRequest, db: Session = Depends(get_db)):
    return bulk_manage_notebooks_service(
        db, payload.notebook_ids, action=payload.action, course_id=payload.course_id,
    )

@router.get("/notebooks/unbound", response_model=list[UnboundNotebookSummary])
def list_unbound_notebooks(db: Session = Depends(get_db)):
    books = db.scalars(select(Notebook).where(Notebook.course_id.is_(None), Notebook.deleted_at.is_(None)).order_by(
        Notebook.created_at.desc(), Notebook.id)).all()
    return [_summary(book) for book in books]

@router.post("/notebooks/unbound", response_model=UnboundNotebookSummary, status_code=201)
def create_unbound_notebook(payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    return _summary(create_unbound_notebook_service(db, payload.title))

@router.get("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def get_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    return _summary(book)

@router.patch("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def rename_unbound_notebook(notebook_id: str, payload: NotebookTitleUpdate,
                            db: Session = Depends(get_db)):
    return _summary(rename_notebook_service(db, notebook_id, payload.title))

@router.delete("/notebooks/unbound/{notebook_id}", status_code=204)
def delete_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    delete_unbound_notebook_service(db, notebook_id)

@router.post("/notebooks/{notebook_id}/bind", response_model=NotebookSummary)
def bind_notebook(notebook_id: str, payload: NotebookBindRequest, db: Session = Depends(get_db)):
    return _summary(bind_notebook_service(db, notebook_id, payload.course_id))

@router.post("/notebooks/{notebook_id}/unbind", response_model=UnboundNotebookSummary)
def unbind_notebook(notebook_id: str, db: Session = Depends(get_db)):
    return _summary(unbind_notebook_service(db, notebook_id))

@router.get("/courses/{course_id}/notebooks", response_model=list[NotebookSummary])
def list_notebooks(course_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    return [_summary(book) for book in list_course_notebooks(db, course_id)
            if book.deleted_at is None]

@router.post("/courses/{course_id}/notebooks", response_model=NotebookSummary, status_code=201)
def create_notebook(course_id: str, payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    return _summary(create_course_notebook_service(db, course_id, payload.title))

@router.post("/notebooks/{notebook_id}/move", response_model=NotebookSummary)
def move_notebook(notebook_id: str, payload: NotebookMoveRequest, db: Session = Depends(get_db)):
    return _summary(move_notebook_service(db, notebook_id, payload.course_id))

@router.delete("/courses/{course_id}/notebooks/{notebook_id}", status_code=204)
def delete_course_notebook(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    delete_course_notebook_service(db, course_id, notebook_id)

@router.get("/notebooks/deleted", response_model=list[NotebookSummary])
def list_deleted_notebooks(db: Session = Depends(get_db)):
    return [_summary(book) for book in db.scalars(select(Notebook).where(
        Notebook.deleted_at.is_not(None)).order_by(Notebook.deleted_at.desc())).all()]

@router.post("/notebooks/{notebook_id}/restore", response_model=NotebookSummary)
def restore_deleted_notebook(notebook_id: str, payload: NotebookRestoreDeletedRequest,
                             db: Session = Depends(get_db)):
    return _summary(restore_deleted_notebook_service(db, notebook_id, payload.course_id))

@router.delete("/notebooks/{notebook_id}/permanent", status_code=204)
def purge_deleted_notebook(notebook_id: str, db: Session = Depends(get_db)) -> None:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is None:
        raise HTTPException(404, "回收站中没有这篇笔记")
    try:
        permanently_delete_notebook(db, book)
    except DeletionConflict as exc:
        raise HTTPException(409, str(exc)) from exc

@router.get("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def get_named_notebook(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    return notebook_outline(db, db.get(Course, course_id), book)

@router.patch("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def rename_notebook(course_id: str, notebook_id: str, payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    book = rename_notebook_service(db, notebook_id, payload.title, course_id=course_id)
    return notebook_outline(db, db.get(Course, course_id), book)

@router.patch("/courses/{course_id}/notebooks/{notebook_id}/order", response_model=NotebookRead)
def reorder_named_notebook(course_id: str, notebook_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    reorder_notebook_service(db, book, payload)
    return notebook_outline(db, db.get(Course, course_id), book)

@router.get("/courses/{course_id}/notebook", response_model=NotebookRead)
def get_notebook(course_id: str, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return notebook_outline(db, course, legacy_book(db, course))

@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    book = legacy_book(db, course)
    reorder_notebook_service(db, book, payload)
    return notebook_outline(db, course, book)
