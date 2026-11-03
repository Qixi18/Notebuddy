"""Notebook document HTTP routes; persistence use cases live in services."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.notebook import BlockSourceRead, NotebookDocumentRead, NotebookDocumentUpdate
from app.services.notebook_document import (
    get_block_sources as get_block_sources_service,
)
from app.services.notebook_document import (
    get_notebook_document as get_notebook_document_service,
)
from app.services.notebook_document import (
    get_notebook_sections as get_notebook_sections_service,
)
from app.services.notebook_document import (
    save_notebook_document_payload,
)

router = APIRouter()

@router.get("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_unbound_document(notebook_id: str, db: Session = Depends(get_db)):
    return get_notebook_document_service(db, notebook_id)

@router.put("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_unbound_document(notebook_id: str, payload: NotebookDocumentUpdate,
                         db: Session = Depends(get_db)):
    return save_notebook_document_payload(
        db, notebook_id, payload, refresh_relations=False,
    )

@router.get("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_notebook_document(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    return get_notebook_document_service(db, notebook_id, course_id=course_id)

@router.put("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_notebook_document(course_id: str, notebook_id: str, payload: NotebookDocumentUpdate,
                          db: Session = Depends(get_db)):
    return save_notebook_document_payload(
        db, notebook_id, payload, course_id=course_id, refresh_relations=True,
    )

@router.get("/notebooks/{notebook_id}/blocks/{block_id}/sources",
            response_model=list[BlockSourceRead])
def get_block_sources(notebook_id: str, block_id: str, db: Session = Depends(get_db)):
    return get_block_sources_service(db, notebook_id, block_id)

@router.get("/courses/{course_id}/notebooks/{notebook_id}/sections")
def get_notebook_sections(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    return get_notebook_sections_service(db, notebook_id, course_id)
