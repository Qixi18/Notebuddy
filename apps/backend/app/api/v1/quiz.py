"""自测卷端点（v6 P10）：列课程待作答卷子 + 提交作答判分。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Quiz
from app.services.quiz import ensure_course_for_quiz, grade_answers, list_course_quizzes

router = APIRouter()


class QuizAnswerEntry(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    answer: str = Field(min_length=1, max_length=500)


class QuizSubmission(BaseModel):
    answers: list[QuizAnswerEntry] = Field(min_length=1, max_length=10)


@router.get("/courses/{course_id}/quizzes")
def list_quizzes(
    course_id: str,
    status: Literal["active", "completed"] = Query(default="active"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_course_for_quiz(db, course_id)
    return list_course_quizzes(db, course_id, status)


@router.post("/quizzes/{quiz_id}/attempts")
def submit_attempts(quiz_id: str, payload: QuizSubmission, db: Session = Depends(get_db)) -> dict[str, Any]:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="自测卷不存在")
    results = grade_answers(db, quiz, [entry.model_dump() for entry in payload.answers])
    db.commit()
    return {
        "quiz_id": quiz.id,
        "status": quiz.status,
        "results": results,
        "score": f"{sum(1 for item in results if item['correct'])}/{len(results)}",
    }
