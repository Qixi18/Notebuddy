"""Application queries and mutations for Forest projections."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Course, Notebook, NotebookRelation, NotebookSection
from app.forest.service import (
    ForestConflict,
    list_forest_courses,
    notebook_relation_display,
    update_profile,
)
from app.notes.notebook import list_course_notebooks, notebook_outline
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_course


def course_tree(db: Session, course_id: str) -> dict:
    course = require_course(db, course_id)
    notebooks = list_course_notebooks(db, course_id)
    return {"course_id": course_id, "notebooks": [
        notebook_outline(db, course, book) for book in notebooks]}


def get_forest(db: Session) -> dict:
    courses = list_forest_courses(db)
    # list_forest_courses initializes missing profile projections.
    db.commit()
    return {"courses": courses}


def search_forest(db: Session, query: str) -> list[dict]:
    term = query.strip()
    if not term:
        return []
    rows = db.execute(select(
        Course.id, Course.name, Notebook.id, Notebook.title,
        NotebookSection.block_id, NotebookSection.heading, NotebookSection.text,
    ).join(Notebook, Notebook.course_id == Course.id)
      .outerjoin(NotebookSection, NotebookSection.notebook_id == Notebook.id)
      .where(Course.deleted_at.is_(None), Notebook.deleted_at.is_(None), or_(
          Notebook.title.icontains(term, autoescape=True),
          NotebookSection.heading.icontains(term, autoescape=True),
          NotebookSection.text.icontains(term, autoescape=True),
      )).order_by(Course.name, Notebook.title, NotebookSection.order).limit(40)).all()
    return [{"course_id": course_id, "course_name": course_name,
             "notebook_id": notebook_id, "block_id": block_id,
             "title": f"{title} · {heading}" if heading else title,
             "snippet": " ".join((text or "").split())[:240]}
            for course_id, course_name, notebook_id, title, block_id, heading, text in rows]


def patch_profile(db: Session, course_id: str, *, expected_revision: int, changes: dict) -> dict:
    course = require_course(db, course_id)
    try:
        update_profile(db, course, expected_revision=expected_revision, changes=changes)
        db.commit()
    except ForestConflict as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return next(row for row in list_forest_courses(db) if row["course_id"] == course_id)


def get_relations(db: Session) -> list[dict]:
    relations = db.scalars(select(NotebookRelation).order_by(
        NotebookRelation.created_at, NotebookRelation.id)).all()
    return [row for relation in relations
            if (row := notebook_relation_display(db, relation)) is not None]
