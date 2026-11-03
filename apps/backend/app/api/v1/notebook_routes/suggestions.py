"""Notebook 路由 · suggestions。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.schemas.notebook import (
    NotebookDocumentRead,
    NotebookEditSuggestionBatchReview,
    NotebookEditSuggestionRead,
    NotebookEditSuggestionReview,
)
from app.services.notebook_suggestions import SuggestionReview
from app.services.notebook_suggestions import (
    apply_course_edit_suggestions as apply_course_edit_suggestions_service,
)
from app.services.notebook_suggestions import (
    list_course_edit_suggestions as list_course_edit_suggestions_service,
)
from app.services.notebook_suggestions import (
    list_notebook_edit_suggestions as list_notebook_edit_suggestions_service,
)
from app.services.notebook_suggestions import (
    review_edit_suggestion as review_edit_suggestion_service,
)

router = APIRouter()


@router.get("/notebooks/{notebook_id}/edit-suggestions",
            response_model=list[NotebookEditSuggestionRead])
def list_edit_suggestions(notebook_id: str, status: str | None = "pending",
                          db: Session = Depends(get_db)):
    return list_notebook_edit_suggestions_service(db, notebook_id, status)

@router.get("/courses/{course_id}/notebook-edit-suggestions",
            response_model=list[NotebookEditSuggestionRead])
def list_course_edit_suggestions(course_id: str, status: str | None = "pending",
                                 db: Session = Depends(get_db)):
    """列出课程内待审核的 Notebook 正文建议，供答疑页集中处理。"""
    ensure_course(db, course_id)
    return list_course_edit_suggestions_service(db, course_id, status)

@router.post("/notebooks/{notebook_id}/edit-suggestions/{suggestion_id}/review",
             response_model=NotebookDocumentRead)
def review_edit_suggestion(notebook_id: str, suggestion_id: str,
                           payload: NotebookEditSuggestionReview,
                           db: Session = Depends(get_db)):
    command = SuggestionReview(
        decision=payload.decision, expected_revision=payload.expected_revision,
        selected_operation_indices=payload.selected_operation_indices,
    )
    return review_edit_suggestion_service(db, notebook_id, suggestion_id, command)

@router.post("/courses/{course_id}/notebook-edit-suggestions/apply-all")
def apply_course_edit_suggestions(course_id: str, payload: NotebookEditSuggestionBatchReview,
                                  db: Session = Depends(get_db)):
    """Apply selected pending Notebook suggestions atomically, one revision per Notebook."""
    ensure_course(db, course_id)
    return apply_course_edit_suggestions_service(db, course_id, payload.suggestion_ids)
