from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Course, Notebook, NotebookRelation, NotebookSection
from app.forest.service import (
    ForestConflict,
    list_forest_courses,
    notebook_relation_display,
    relation_anchor_fingerprint,
    update_profile,
)
from app.notes.notebook import list_course_notebooks, notebook_outline
from app.schemas.forest import (
    ForestCourseRead,
    ForestCourseUpdate,
    ForestRead,
    ForestSearchRead,
    NotebookRelationCreate,
    NotebookRelationRead,
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
    rows = db.execute(
        select(
            Course.id, Course.name, Notebook.id, Notebook.title,
            NotebookSection.block_id, NotebookSection.heading, NotebookSection.text,
        )
        .join(Notebook, Notebook.course_id == Course.id)
        .outerjoin(NotebookSection, NotebookSection.notebook_id == Notebook.id)
        .where(
            Course.deleted_at.is_(None),
            Notebook.deleted_at.is_(None),
            or_(
                Notebook.title.icontains(term, autoescape=True),
                NotebookSection.heading.icontains(term, autoescape=True),
                NotebookSection.text.icontains(term, autoescape=True),
            ),
        )
        .order_by(Course.name, Notebook.title, NotebookSection.order)
        .limit(40)
    ).all()
    results: list[dict] = []
    for course_id, course_name, notebook_id, title, block_id, heading, text in rows:
        snippet = " ".join((text or "").split())[:240]
        results.append({
            "course_id": course_id,
            "course_name": course_name,
            "notebook_id": notebook_id,
            "block_id": block_id,
            "title": f"{title} · {heading}" if heading else title,
            "snippet": snippet,
        })
    return results


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


@router.get("/forest/relations", response_model=list[NotebookRelationRead])
def get_relations(db: Session = Depends(get_db)) -> list[dict]:
    relations = db.scalars(select(NotebookRelation).order_by(
        NotebookRelation.created_at, NotebookRelation.id,
    )).all()
    return [
        row for relation in relations
        if (row := notebook_relation_display(db, relation)) is not None
    ]


@router.post("/forest/relations", response_model=NotebookRelationRead, status_code=201)
def create_relation(payload: NotebookRelationCreate, db: Session = Depends(get_db)) -> dict:
    source = db.get(Notebook, payload.source_notebook_id)
    target = db.get(Notebook, payload.target_notebook_id)
    for notebook in (source, target):
        if notebook is None or notebook.deleted_at is not None or notebook.course_id is None:
            raise HTTPException(status_code=404, detail="关系引用的笔记不存在或尚未归入课程")
    assert source is not None and target is not None
    fingerprints = _validate_relation_anchors(source, target, payload.source_block_id, payload.target_block_id)
    if source.id == target.id or source.course_id == target.course_id:
        raise HTTPException(status_code=422, detail="跨课关系必须引用不同课程中的两本笔记")
    existing = db.scalar(select(NotebookRelation).where(
        NotebookRelation.source_notebook_id == payload.source_notebook_id,
        NotebookRelation.target_notebook_id == payload.target_notebook_id,
        NotebookRelation.relation_type == payload.relation_type,
        NotebookRelation.source_block_id == payload.source_block_id,
        NotebookRelation.target_block_id == payload.target_block_id,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail="这两本笔记的同类型关系已存在")
    relation = NotebookRelation(
        source_notebook_id=payload.source_notebook_id,
        target_notebook_id=payload.target_notebook_id,
        relation_type=payload.relation_type,
        description=payload.reason,
        source_block_id=payload.source_block_id,
        target_block_id=payload.target_block_id,
        source_fingerprint=fingerprints[0], target_fingerprint=fingerprints[1],
    )
    db.add(relation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="这两本笔记的同类型关系已存在") from exc
    db.refresh(relation)
    display = notebook_relation_display(db, relation)
    if display is None:
        raise HTTPException(status_code=409, detail="关系创建后无法展示，请检查课程归属")
    return display


def _validate_relation_anchors(source, target, source_block_id, target_block_id):
    fingerprints = (
        relation_anchor_fingerprint(source, source_block_id),
        relation_anchor_fingerprint(target, target_block_id),
    )
    if any(block_id is not None and fingerprint is None for block_id, fingerprint in zip(
        (source_block_id, target_block_id), fingerprints, strict=True,
    )):
        raise HTTPException(422, "关联小节不存在于所选笔记的当前正文，请重新选择")
    return fingerprints


@router.post("/forest/relations/{relation_id}/refresh", response_model=NotebookRelationRead)
def refresh_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    relation = db.get(NotebookRelation, relation_id)
    if relation is None or notebook_relation_display(db, relation) is None:
        raise HTTPException(404, "关系不存在或笔记已不可用")
    source = db.get(Notebook, relation.source_notebook_id)
    target = db.get(Notebook, relation.target_notebook_id)
    relation.source_fingerprint, relation.target_fingerprint = _validate_relation_anchors(
        source, target, relation.source_block_id, relation.target_block_id,
    )
    db.commit()
    return notebook_relation_display(db, relation)


@router.delete("/forest/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    relation = db.get(NotebookRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="关系不存在")
    db.delete(relation)
    db.commit()
    return {"deleted": True}
