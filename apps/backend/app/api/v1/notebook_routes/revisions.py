"""Notebook revision HTTP adapters; document history use cases live in services."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.notebook import (
    NotebookDocumentRead,
    NotebookRestoreRequest,
    NotebookRevisionRead,
    NotebookRevisionSummary,
)
from app.services.notebook_document import (
    get_notebook_revision,
    restore_notebook_document_payload,
)
from app.services.notebook_document import (
    list_notebook_revisions as list_notebook_revisions_service,
)

router = APIRouter()


@router.get("/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_unbound_revisions(notebook_id: str, db: Session = Depends(get_db)):
    return list_notebook_revisions_service(db, notebook_id)


@router.get("/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_unbound_revision(notebook_id: str, revision: int,
                          db: Session = Depends(get_db)):
    return get_notebook_revision(db, notebook_id, revision)


@router.post("/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_unbound_revision(notebook_id: str, revision: int,
                             payload: NotebookRestoreRequest,
                             db: Session = Depends(get_db)):
    return restore_notebook_document_payload(
        db, notebook_id, revision, payload.expected_revision,
        refresh_relations=False,
    )


@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_notebook_revisions(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    return list_notebook_revisions_service(db, notebook_id, course_id=course_id)


@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_notebook_revision(course_id: str, notebook_id: str, revision: int,
                           db: Session = Depends(get_db)):
    return get_notebook_revision(db, notebook_id, revision, course_id=course_id)


@router.post("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_notebook_revision(course_id: str, notebook_id: str, revision: int,
                              payload: NotebookRestoreRequest, db: Session = Depends(get_db)):
    return restore_notebook_document_payload(
        db, notebook_id, revision, payload.expected_revision,
        course_id=course_id, refresh_relations=True,
    )
