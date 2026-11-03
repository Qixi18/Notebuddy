"""Notebook 路由 · lifecycle。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
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
    get_course_notebooks as get_course_notebooks_service,
)
from app.services.notebook_lifecycle import (
    get_notebook_outline,
    permanently_delete_notebook_service,
    reorder_notebook_outline,
)
from app.services.notebook_lifecycle import (
    get_unbound_notebook as get_unbound_notebook_service,
)
from app.services.notebook_lifecycle import (
    list_deleted_notebooks as list_deleted_notebooks_service,
)
from app.services.notebook_lifecycle import (
    list_unbound_notebooks as list_unbound_notebooks_service,
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

from .common import _summary

router = APIRouter()

@router.post("/notebooks/bulk-manage")
def bulk_manage_notebooks(payload: NotebookBulkManageRequest, db: Session = Depends(get_db)):
    return bulk_manage_notebooks_service(
        db, payload.notebook_ids, action=payload.action, course_id=payload.course_id,
    )

@router.get("/notebooks/unbound", response_model=list[UnboundNotebookSummary])
def list_unbound_notebooks(db: Session = Depends(get_db)):
    return [_summary(book) for book in list_unbound_notebooks_service(db)]

@router.post("/notebooks/unbound", response_model=UnboundNotebookSummary, status_code=201)
def create_unbound_notebook(payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    return _summary(create_unbound_notebook_service(db, payload.title))

@router.get("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def get_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    return _summary(get_unbound_notebook_service(db, notebook_id))

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
    return [_summary(book) for book in get_course_notebooks_service(db, course_id)]

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
    return [_summary(book) for book in list_deleted_notebooks_service(db)]

@router.post("/notebooks/{notebook_id}/restore", response_model=NotebookSummary)
def restore_deleted_notebook(notebook_id: str, payload: NotebookRestoreDeletedRequest,
                             db: Session = Depends(get_db)):
    return _summary(restore_deleted_notebook_service(db, notebook_id, payload.course_id))

@router.delete("/notebooks/{notebook_id}/permanent", status_code=204)
def purge_deleted_notebook(notebook_id: str, db: Session = Depends(get_db)) -> None:
    permanently_delete_notebook_service(db, notebook_id)

@router.get("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def get_named_notebook(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    return get_notebook_outline(db, course_id, notebook_id)

@router.patch("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def rename_notebook(course_id: str, notebook_id: str, payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    rename_notebook_service(db, notebook_id, payload.title, course_id=course_id)
    return get_notebook_outline(db, course_id, notebook_id)

@router.patch("/courses/{course_id}/notebooks/{notebook_id}/order", response_model=NotebookRead)
def reorder_named_notebook(course_id: str, notebook_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    return reorder_notebook_outline(db, course_id, notebook_id,
                                    payload.material_ids, payload.expected_order_revision)

@router.get("/courses/{course_id}/notebook", response_model=NotebookRead)
def get_notebook(course_id: str, db: Session = Depends(get_db)):
    return get_notebook_outline(db, course_id)

@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    return reorder_notebook_outline(db, course_id, None,
                                    payload.material_ids, payload.expected_order_revision)
