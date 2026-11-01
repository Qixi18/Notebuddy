"""Notebook 路由 · documents。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook
from app.notes.document import (
    DocumentValidationError,
    document_to_blocks,
    legacy_blocks_to_document,
    load_document,
    normalize_document,
)
from app.notes.index import sections_for_notebook
from app.notes.store import DocumentConflict, block_source_payload, write_document
from app.schemas.notebook import BlockSourceRead, NotebookDocumentRead, NotebookDocumentUpdate

from .common import (
    _ensure_document_image_ownership,
    ensure_notebook,
)

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
    if payload.blocks is not None and not load_document(book.document_json).legacy:
        raise HTTPException(409, "笔记已使用新版编辑器，请刷新页面后继续编辑")
    try:
        if payload.content is not None:
            content = payload.content
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise HTTPException(422, "正文块编号不能重复")
            content = legacy_blocks_to_document(blocks)
        _ensure_document_image_ownership(db, notebook_id, normalize_document(content))
        next_revision, stored = write_document(
            db, book, content, expected_revision=payload.expected_revision,
            origin="autosave", legacy_compatible=payload.blocks is not None,
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
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
    if payload.blocks is not None and not load_document(book.document_json).legacy:
        raise HTTPException(409, "笔记已使用新版编辑器，请刷新页面后继续编辑")
    try:
        if payload.content is not None:
            content = payload.content
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise HTTPException(422, "正文块编号不能重复")
            content = legacy_blocks_to_document(blocks)
        _ensure_document_image_ownership(db, notebook_id, normalize_document(content))
        next_revision, stored = write_document(
            db, book, content, expected_revision=payload.expected_revision,
            origin="autosave", legacy_compatible=payload.blocks is not None,
            refresh_relations=True,
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
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
