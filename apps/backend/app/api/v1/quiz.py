"""复习面板端点（v6 §7 学习闭环）：自测卷、题目用户状态、复习产物（提纲/对比）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Quiz
from app.services.quiz import (
    ensure_course_for_quiz,
    get_quiz_for_client,
    grade_answers,
    list_course_mistakes,
    list_course_quizzes,
    list_review_artifacts,
    set_quiz_item_flags,
    update_review_artifact,
)

router = APIRouter()


class QuizAnswerEntry(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    answer: str = Field(min_length=1, max_length=500)


class QuizSubmission(BaseModel):
    answers: list[QuizAnswerEntry] = Field(min_length=1, max_length=10)


class QuizItemFlags(BaseModel):
    favorite: bool | None = None
    marked: bool | None = None
    dismissed: bool | None = None


class ArtifactUpdate(BaseModel):
    favorite: bool | None = None
    dismissed: bool | None = None


@router.get("/courses/{course_id}/quizzes")
def list_quizzes(
    course_id: str,
    status: Literal["active", "completed"] = Query(default="active"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_course_for_quiz(db, course_id)
    return list_course_quizzes(db, course_id, status)


@router.get("/courses/{course_id}/quiz-mistakes")
def list_mistakes(
    course_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """复习面板·题目：最近一次仍错（或被收藏/标记）且未移出的题，按最近作答倒序。"""
    ensure_course_for_quiz(db, course_id)
    return list_course_mistakes(db, course_id, limit)


@router.patch("/quiz-items/{item_id}/flags")
def update_item_flags(item_id: str, payload: QuizItemFlags, db: Session = Depends(get_db)) -> dict[str, Any]:
    """收藏 / 标记 / 移出复习（dismissed）：复习面板与答题卡的题目级用户状态。"""
    updated = set_quiz_item_flags(
        db, item_id, favorite=payload.favorite, marked=payload.marked, dismissed=payload.dismissed,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return updated


@router.get("/courses/{course_id}/review-artifacts")
def list_artifacts(
    course_id: str,
    kind: Literal["review_outline", "concept_contrast"] | None = Query(default=None),
    include_dismissed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """复习产物（复习提纲 / 易混概念），按创建时间倒序；默认不含已移出的。"""
    ensure_course_for_quiz(db, course_id)
    return list_review_artifacts(db, course_id, kind, limit, include_dismissed=include_dismissed)


@router.get("/review-artifacts")
def list_artifacts_by_ids(
    ids: str = Query(min_length=1, description="逗号分隔的产物 id"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """按 id 批量取产物状态：技能卡挂载时回读收藏真源（快照里的 favorite 是生成时刻旧值）。"""
    wanted = [entry.strip() for entry in ids.split(",") if entry.strip()][:200]
    if not wanted:
        return []
    return list_review_artifacts(db, ids=wanted)


@router.patch("/review-artifacts/{artifact_id}")
def update_artifact(artifact_id: str, payload: ArtifactUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    """收藏 / 移出复习（软移除）：数据与会话卡片均保留，随时可恢复。"""
    updated = update_review_artifact(db, artifact_id, favorite=payload.favorite, dismissed=payload.dismissed)
    if updated is None:
        raise HTTPException(status_code=404, detail="复习产物不存在")
    return updated


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """单卷直取：答题卡的建议只有卷子 id，不在 active 列表（已完成/超出窗口）时按 id 补拉。"""
    quiz = get_quiz_for_client(db, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="自测卷不存在")
    return quiz


@router.post("/quizzes/{quiz_id}/attempts")
def submit_attempts(quiz_id: str, payload: QuizSubmission, db: Session = Depends(get_db)) -> dict[str, Any]:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="自测卷不存在")
    results = grade_answers(db, quiz, [entry.model_dump() for entry in payload.answers])
    db.commit()
    return {
        "quiz_id": quiz.id,
        "status": quiz.status,
        "results": results,
        "score": f"{sum(1 for item in results if item['correct'])}/{len(results)}",
    }
