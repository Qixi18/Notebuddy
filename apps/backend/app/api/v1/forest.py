from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Course, Notebook, NotebookRelation, NotebookSection
from app.forest.service import (
    ForestConflict,
    list_forest_courses,
    notebook_relation_display,
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
from app.services.notebook_relations import (
    create_forest_relation,
    delete_notebook_relation,
    refresh_forest_relation,
)

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
    return create_forest_relation(
        db, source_id=payload.source_notebook_id, target_id=payload.target_notebook_id,
        relation_type=payload.relation_type, reason=payload.reason,
        source_block_id=payload.source_block_id, target_block_id=payload.target_block_id,
    )


@router.post("/forest/relations/{relation_id}/refresh", response_model=NotebookRelationRead)
def refresh_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    return refresh_forest_relation(db, relation_id)


@router.delete("/forest/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    delete_notebook_relation(db, relation_id)
    return {"deleted": True}
