from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.schemas.api import TermExplanationRequest, TermExplanationResponse
from app.services.terms import explain_term_from_course

router = APIRouter()


@router.post("/courses/{course_id}/terms/explain", response_model=TermExplanationResponse)
def explain_term(
    course_id: str, payload: TermExplanationRequest, db: Session = Depends(get_db)
) -> TermExplanationResponse:
    ensure_course(db, course_id)
    return explain_term_from_course(db, course_id=course_id, payload=payload)
