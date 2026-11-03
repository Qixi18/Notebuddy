"""Notebook document HTTP routes; persistence use cases live in services."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook
from app.notes.document import document_to_blocks, load_document
from app.notes.index import sections_for_notebook
from app.notes.store import block_source_payload
from app.schemas.notebook import BlockSourceRead, NotebookDocumentRead, NotebookDocumentUpdate
from app.services.notebook_document import save_notebook_document

from .common import ensure_notebook

router = APIRouter()

@router.get("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_unbound_document(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    stored = load_document(book.document_json)
    return {"schema_version": 2, "content": stored.content,
            "blocks": document_to_blocks(stored.content),
            "revision": book.document_revision, "updated_at": book.updated_at,
            "warning": stored.warning}

@router.put("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_unbound_document(notebook_id: str, payload: NotebookDocumentUpdate,
                         db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    next_revision, stored = save_notebook_document(
        db, book, payload, refresh_relations=False,
    )
    return {"schema_version": 2, "content": stored,
            "blocks": document_to_blocks(stored), "revision": next_revision,
            "updated_at": book.updated_at}

@router.get("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_notebook_document(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    stored = load_document(book.document_json)
    return {"schema_version": 2, "content": stored.content,
            "blocks": document_to_blocks(stored.content),
            "revision": book.document_revision, "updated_at": book.updated_at,
            "warning": stored.warning}

@router.put("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_notebook_document(course_id: str, notebook_id: str, payload: NotebookDocumentUpdate,
                          db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    next_revision, stored = save_notebook_document(
        db, book, payload, refresh_relations=True,
    )
    return {"schema_version": 2, "content": stored,
            "blocks": document_to_blocks(stored),
            "revision": next_revision, "updated_at": book.updated_at}

@router.get("/notebooks/{notebook_id}/blocks/{block_id}/sources",
            response_model=list[BlockSourceRead])
def get_block_sources(notebook_id: str, block_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    return block_source_payload(db, notebook_id, block_id)

@router.get("/courses/{course_id}/notebooks/{notebook_id}/sections")
def get_notebook_sections(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return [{
        "block_id": row.block_id, "heading": row.heading, "level": row.level,
        "order": row.order, "revision": row.revision, "excerpt": row.text[:300],
    } for row in sections_for_notebook(db, notebook_id)]
