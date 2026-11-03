"""Notebook revision HTTP routes; restoration is handled by the document service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook
from app.notes.document import document_to_blocks, load_document
from app.notes.history import get_snapshot, list_snapshots
from app.schemas.notebook import (
    NotebookDocumentRead,
    NotebookRestoreRequest,
    NotebookRevisionRead,
    NotebookRevisionSummary,
)
from app.services.notebook_document import restore_notebook_document

from .common import ensure_notebook

router = APIRouter()

@router.get("/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_unbound_revisions(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    return list_snapshots(db, notebook_id)

@router.get("/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_unbound_revision(notebook_id: str, revision: int,
                          db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    return {"revision": snapshot.revision, "origin": snapshot.origin,
            "created_at": snapshot.created_at, "schema_version": 2,
            "content": stored.content}

@router.post("/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_unbound_revision(notebook_id: str, revision: int,
                             payload: NotebookRestoreRequest,
                             db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    next_revision, content = restore_notebook_document(
        db, book, revision, payload.expected_revision, refresh_relations=False,
    )
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content), "revision": next_revision,
            "updated_at": book.updated_at}

@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_notebook_revisions(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return list_snapshots(db, notebook_id)

@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_notebook_revision(course_id: str, notebook_id: str, revision: int,
                           db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    return {"revision": snapshot.revision, "origin": snapshot.origin,
            "created_at": snapshot.created_at, "schema_version": 2,
            "content": stored.content}

@router.post("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_notebook_revision(course_id: str, notebook_id: str, revision: int,
                              payload: NotebookRestoreRequest, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    next_revision, content = restore_notebook_document(
        db, book, revision, payload.expected_revision, refresh_relations=True,
    )
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": next_revision, "updated_at": book.updated_at}
