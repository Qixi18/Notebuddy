"""Notebook 路由 · suggestions。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Notebook, NotebookEditSuggestion
from app.notes.document import load_document
from app.schemas.notebook import (
    NotebookDocumentRead,
    NotebookEditSuggestionBatchReview,
    NotebookEditSuggestionRead,
    NotebookEditSuggestionReview,
)
from app.services.errors import ApplicationError
from app.services.notebook_suggestions import SuggestionReview
from app.services.notebook_suggestions import (
    apply_course_edit_suggestions as apply_course_edit_suggestions_service,
)
from app.services.notebook_suggestions import (
    review_edit_suggestion as review_edit_suggestion_service,
)

router = APIRouter()


def _service_result(callable_, *args):
    try:
        return callable_(*args)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

@router.get("/notebooks/{notebook_id}/edit-suggestions",
            response_model=list[NotebookEditSuggestionRead])
def list_edit_suggestions(notebook_id: str, status: str | None = "pending",
                          db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    query = select(NotebookEditSuggestion).where(
        NotebookEditSuggestion.notebook_id == notebook_id,
    )
    if status:
        query = query.where(NotebookEditSuggestion.status == status)
    rows = db.scalars(query.order_by(
        NotebookEditSuggestion.created_at.desc()).limit(50)).all()
    result = []
    for row in rows:
        try:
            operations = json.loads(row.ops_json)
            proposed = load_document(row.proposed_document_json)
            result.append({
                "id": row.id, "notebook_id": row.notebook_id,
                "base_revision": row.base_revision, "rationale": row.rationale,
                "operations": operations if isinstance(operations, list) else [],
                "proposed_content": proposed.content if proposed.warning is None else None,
                "status": row.status, "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
            })
        except (TypeError, ValueError):
            result.append({
                "id": row.id, "notebook_id": row.notebook_id,
                "base_revision": row.base_revision, "rationale": row.rationale,
                "operations": [], "proposed_content": None,
                "status": row.status, "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
            })
    return result

@router.get("/courses/{course_id}/notebook-edit-suggestions",
            response_model=list[NotebookEditSuggestionRead])
def list_course_edit_suggestions(course_id: str, status: str | None = "pending",
                                 db: Session = Depends(get_db)):
    """列出课程内待审核的 Notebook 正文建议，供答疑页集中处理。"""
    ensure_course(db, course_id)
    rows = db.execute(
        select(NotebookEditSuggestion, Notebook.title)
        .join(Notebook, Notebook.id == NotebookEditSuggestion.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
               *([NotebookEditSuggestion.status == status] if status else []))
        .order_by(NotebookEditSuggestion.created_at.desc())
        .limit(200)
    ).all()
    result = []
    for row, notebook_title in rows:
        try:
            operations = json.loads(row.ops_json)
            proposed = load_document(row.proposed_document_json)
            proposed_content = proposed.content if proposed.warning is None else None
        except (TypeError, ValueError):
            operations, proposed_content = [], None
        result.append({
            "id": row.id, "notebook_id": row.notebook_id, "notebook_title": notebook_title,
            "base_revision": row.base_revision, "rationale": row.rationale,
            "operations": operations if isinstance(operations, list) else [],
            "proposed_content": proposed_content, "status": row.status,
            "created_at": row.created_at, "reviewed_at": row.reviewed_at,
        })
    return result

@router.post("/notebooks/{notebook_id}/edit-suggestions/{suggestion_id}/review",
             response_model=NotebookDocumentRead)
def review_edit_suggestion(notebook_id: str, suggestion_id: str,
                           payload: NotebookEditSuggestionReview,
                           db: Session = Depends(get_db)):
    command = SuggestionReview(
        decision=payload.decision, expected_revision=payload.expected_revision,
        selected_operation_indices=payload.selected_operation_indices,
    )
    return _service_result(review_edit_suggestion_service, db, notebook_id, suggestion_id, command)

@router.post("/courses/{course_id}/notebook-edit-suggestions/apply-all")
def apply_course_edit_suggestions(course_id: str, payload: NotebookEditSuggestionBatchReview,
                                  db: Session = Depends(get_db)):
    """Apply selected pending Notebook suggestions atomically, one revision per Notebook."""
    ensure_course(db, course_id)
    return _service_result(apply_course_edit_suggestions_service, db, course_id, payload.suggestion_ids)
