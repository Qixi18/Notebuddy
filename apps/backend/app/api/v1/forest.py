from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course, ensure_note
from app.db.database import get_db
from app.db.models import Course, CrossCourseRelation, Note
from app.forest.service import (
    ForestConflict,
    active_note_sources,
    list_forest_courses,
    note_is_visible,
    relation_display,
    relation_fingerprint,
    update_profile,
    visible_note_predicate,
)
from app.notes.notebook import list_course_notebooks, notebook_outline
from app.schemas.forest import (
    CrossCourseRelationCreate,
    CrossCourseRelationRead,
    CrossCourseRelationReview,
    ForestCourseRead,
    ForestCourseUpdate,
    ForestRead,
    ForestSearchRead,
)
from app.schemas.notebook import CourseTreeRead

router = APIRouter()


@router.get("/forest/courses/{course_id}/tree", response_model=CourseTreeRead)
def course_tree(course_id: str, db: Session = Depends(get_db)) -> dict:
    course = ensure_course(db, course_id)
    return {"course_id": course_id, "notebooks": [
        notebook_outline(db, course, book) for book in list_course_notebooks(db, course_id)]}


@router.get("/forest", response_model=ForestRead)
def get_forest(db: Session = Depends(get_db)) -> dict:
    courses = list_forest_courses(db)
    db.commit()
    return {"courses": courses}


@router.get("/forest/search", response_model=list[ForestSearchRead])
def search_forest(
    q: str = Query(min_length=1, max_length=200), db: Session = Depends(get_db)
) -> list[dict]:
    term = q.strip()
    if not term:
        return []
    rows = (
        db.execute(
            select(
                Course.id.label("course_id"),
                Course.name.label("course_name"),
                Note.id.label("note_id"),
                Note.title,
                Note.material_id,
                Note.notebook_id,
            )
            .join(Note, Note.course_id == Course.id)
            .where(
                Course.deleted_at.is_(None),
                visible_note_predicate(),
                or_(
                    Note.title.icontains(term, autoescape=True),
                    Course.name.icontains(term, autoescape=True),
                ),
            )
            .order_by(Course.name, Note.title, Note.id)
            .limit(40)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


@router.patch("/forest/courses/{course_id}", response_model=ForestCourseRead)
def patch_profile(
    course_id: str, payload: ForestCourseUpdate, db: Session = Depends(get_db)
) -> dict:
    course = ensure_course(db, course_id)
    try:
        update_profile(
            db,
            course,
            expected_revision=payload.expected_revision,
            changes=payload.model_dump(exclude_unset=True, exclude={"expected_revision"}),
        )
        db.commit()
    except ForestConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return next(row for row in list_forest_courses(db) if row["course_id"] == course_id)


@router.get("/forest/relations", response_model=list[CrossCourseRelationRead])
def get_relations(
    status: Literal["confirmed", "pending", "rejected", "all"] = "confirmed",
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(CrossCourseRelation).order_by(
        CrossCourseRelation.created_at, CrossCourseRelation.id
    )
    if status != "all":
        query = query.where(CrossCourseRelation.status == status)
    return [
        row
        for relation in db.scalars(query).all()
        if (row := relation_display(db, relation)) is not None
    ]


@router.post("/forest/relations", response_model=CrossCourseRelationRead, status_code=201)
def create_relation(payload: CrossCourseRelationCreate, db: Session = Depends(get_db)) -> dict:
    source, target = (
        ensure_note(db, payload.source_note_id),
        ensure_note(db, payload.target_note_id),
    )
    if not note_is_visible(db, source) or not note_is_visible(db, target):
        raise HTTPException(status_code=404, detail="关系所引用的笔记或资料已移除")
    if source.id == target.id or source.course_id == target.course_id:
        raise HTTPException(status_code=422, detail="跨课关系必须引用不同课程中的两篇真实笔记")
    if payload.relation_type == "related" and source.id > target.id:
        source, target = target, source
    source_refs, target_refs = active_note_sources(db, source), active_note_sources(db, target)
    if not source_refs or not target_refs:
        raise HTTPException(status_code=422, detail="两端笔记都需要可核对的当前课件来源")
    values = {
        "source_course_id": source.course_id,
        "target_course_id": target.course_id,
        "source_note_id": source.id,
        "target_note_id": target.id,
        "source_revision": source.revision_number,
        "target_revision": target.revision_number,
        "relation_type": payload.relation_type,
        "reason": payload.reason,
        "status": "confirmed",
        "origin": "manual",
        "activation_mode": "manual",
        "evidence_fingerprint": relation_fingerprint(db, source, target, [r.id for r in source_refs], [r.id for r in target_refs]),
        "source_ref_ids_json": json.dumps([ref.id for ref in source_refs]),
        "target_ref_ids_json": json.dumps([ref.id for ref in target_refs]),
    }
    existing = db.scalar(
        select(CrossCourseRelation).where(
            CrossCourseRelation.source_note_id == source.id,
            CrossCourseRelation.target_note_id == target.id,
            CrossCourseRelation.relation_type == payload.relation_type,
        )
    )
    if existing is not None:
        display = relation_display(db, existing)
        if display is None or (not display["stale"] and existing.status != "rejected"):
            raise HTTPException(status_code=409, detail="这两篇笔记的同类型关系已存在")
        # Reconnecting is explicit user confirmation of the current evidence. Keep
        # the relationship ID while protecting against another simultaneous review.
        changed = db.execute(
            update(CrossCourseRelation)
            .where(
                CrossCourseRelation.id == existing.id,
                CrossCourseRelation.source_revision == existing.source_revision,
                CrossCourseRelation.target_revision == existing.target_revision,
                CrossCourseRelation.source_ref_ids_json == existing.source_ref_ids_json,
                CrossCourseRelation.target_ref_ids_json == existing.target_ref_ids_json,
                *[
                    exists(
                        select(1).where(
                            Note.id == note.id, Note.revision_number == note.revision_number
                        )
                    )
                    for note in (source, target)
                ],
            )
            .values(**values)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="关系或笔记已变化，请刷新后重新连接")
        relation = existing
    else:
        relation = CrossCourseRelation(**values)
        db.add(relation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="这两篇笔记的同类型关系已存在") from exc
    db.refresh(relation)
    return relation_display(db, relation)


def _ensure_relation(db: Session, relation_id: str) -> tuple[CrossCourseRelation, dict]:
    relation = db.get(CrossCourseRelation, relation_id)
    display = relation_display(db, relation) if relation is not None else None
    if display is None:
        raise HTTPException(status_code=404, detail="跨课关系不存在或引用的课程/资料已移除")
    return relation, display


@router.post("/forest/relations/{relation_id}/review", response_model=CrossCourseRelationRead)
def review_relation(
    relation_id: str, payload: CrossCourseRelationReview, db: Session = Depends(get_db)
) -> dict:
    relation, display = _ensure_relation(db, relation_id)
    if payload.decision == "confirm":
        if display["stale"]:
            raise HTTPException(
                status_code=409, detail="笔记版本或来源已变化，请重新建立或生成关系"
            )
        predicates = [
            exists(select(1).where(Note.id == note_id, Note.revision_number == revision))
            for note_id, revision in [
                (relation.source_note_id, relation.source_revision),
                (relation.target_note_id, relation.target_revision),
            ]
        ]
        changed = db.execute(
            update(CrossCourseRelation)
            .where(CrossCourseRelation.id == relation_id, *predicates)
            .values(status="confirmed", activation_mode="manual")
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="笔记版本已变化，请刷新后重试")
    else:
        relation.status = "rejected"
    db.commit()
    db.refresh(relation)
    return relation_display(db, relation)


@router.delete("/forest/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    relation, _ = _ensure_relation(db, relation_id)
    relation.status = "rejected"
    db.commit()
    return {"deleted": True}
