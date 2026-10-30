"""Forest domain rules over Notebook body and Notebook relations.

No function here reads or writes a legacy Note body.  Course profiles are
unchanged; counts and relations are derived from Notebook / NotebookSection.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    Course,
    ForestCourseProfile,
    Material,
    Notebook,
    NotebookRelation,
    NotebookSection,
)


class ForestConflict(ValueError):
    pass


HOME_COURSE_LIMIT = 3


def _learning_count():
    counted = aliased(ForestCourseProfile)
    return (
        select(func.count())
        .select_from(counted)
        .join(Course, Course.id == counted.course_id)
        .where(Course.deleted_at.is_(None), counted.learning_state == "learning")
        .scalar_subquery()
    )


def _json_strings(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []


def ensure_profile(db: Session, course: Course, *, auto_home: bool = False) -> ForestCourseProfile:
    """Initialize once; a later upload never changes a user's learning state."""
    profile = db.get(ForestCourseProfile, course.id)
    if profile is not None:
        return profile
    last_position = db.scalar(select(func.max(ForestCourseProfile.position)))
    position = int(last_position) + 1 if last_position is not None else 0
    has_material = (
        db.scalar(
            select(Material.id)
            .join(Notebook, Notebook.id == Material.notebook_id)
            .where(Notebook.course_id == course.id, Notebook.deleted_at.is_(None),
                   Material.deleted_at.is_(None))
            .limit(1)
        )
        is not None
    )
    db.execute(
        insert(ForestCourseProfile)
        .values(
            course_id=course.id,
            position=position,
            learning_state=(
                case((_learning_count() < HOME_COURSE_LIMIT, "learning"), else_="planned")
                if has_material or auto_home else "planned"
            ),
        )
        .on_conflict_do_nothing(index_elements=[ForestCourseProfile.course_id])
    )
    return db.get(ForestCourseProfile, course.id, populate_existing=True)


def list_forest_courses(db: Session) -> list[dict]:
    courses = list(
        db.scalars(
            select(Course).where(Course.deleted_at.is_(None)).order_by(Course.created_at, Course.id)
        ).all()
    )
    notebook_counts = dict(
        db.execute(
            select(Notebook.course_id, func.count())
            .where(Notebook.deleted_at.is_(None), Notebook.course_id.is_not(None))
            .group_by(Notebook.course_id)
        ).all()
    )
    section_counts = dict(
        db.execute(
            select(Notebook.course_id, func.count(NotebookSection.id))
            .join(Notebook, Notebook.id == NotebookSection.notebook_id)
            .where(Notebook.course_id.is_not(None), Notebook.deleted_at.is_(None))
            .group_by(Notebook.course_id)
        ).all()
    )
    material_counts = dict(
        db.execute(
            select(Notebook.course_id, func.count(Material.id))
            .join(Material, Material.notebook_id == Notebook.id)
            .where(Notebook.deleted_at.is_(None), Material.deleted_at.is_(None))
            .group_by(Notebook.course_id)
        ).all()
    )
    rows = []
    for course in courses:
        profile = ensure_profile(db, course)
        rows.append(
            {
                "course_id": course.id,
                "name": course.name,
                "semester": profile.semester,
                "level": profile.level,
                "learning_state": profile.learning_state,
                "position": profile.position,
                "revision": profile.revision,
                "note_count": int(section_counts.get(course.id, 0)),
                "section_count": int(section_counts.get(course.id, 0)),
                "notebook_count": int(notebook_counts.get(course.id, 0)),
                "material_count": int(material_counts.get(course.id, 0)),
                "prerequisites": _json_strings(profile.prerequisites_json),
            }
        )
    return sorted(rows, key=lambda row: (row["position"], row["course_id"]))


def update_profile(db: Session, course: Course, *, expected_revision: int, changes: dict) -> None:
    ensure_profile(db, course)
    values = dict(changes)
    if "prerequisites" in values:
        values["prerequisites_json"] = json.dumps(values.pop("prerequisites"), ensure_ascii=False)
    values["revision"] = ForestCourseProfile.revision + 1
    criteria = [
        ForestCourseProfile.course_id == course.id,
        ForestCourseProfile.revision == expected_revision,
    ]
    if changes.get("learning_state") == "learning":
        # Keep the count in the write statement: two readers may both have seen
        # the final free slot, but only one writer may claim it.
        criteria.append(or_(
            ForestCourseProfile.learning_state == "learning",
            _learning_count() < HOME_COURSE_LIMIT,
        ))
    updated = db.execute(
        update(ForestCourseProfile)
        .where(*criteria)
        .values(**values)
    )
    if updated.rowcount != 1:
        current = db.get(ForestCourseProfile, course.id, populate_existing=True)
        if (
            current is not None
            and current.revision == expected_revision
            and changes.get("learning_state") == "learning"
            and current.learning_state != "learning"
        ):
            raise ForestConflict("首页最多放 3 棵正在学的课程树，请先移出一门课程后重试")
        raise ForestConflict("森林课程信息已被修改，请刷新后重试")


def prepare_course_restore(db: Session, course: Course) -> None:
    """Restore all course data while keeping an already full home selection."""
    ensure_profile(db, course)
    db.execute(
        update(ForestCourseProfile)
        .where(
            ForestCourseProfile.course_id == course.id,
            ForestCourseProfile.learning_state == "learning",
            _learning_count() >= HOME_COURSE_LIMIT,
        )
        .values(learning_state="planned", revision=ForestCourseProfile.revision + 1)
    )


def notebook_relation_display(db: Session, relation: NotebookRelation) -> dict | None:
    source = db.get(Notebook, relation.source_notebook_id)
    target = db.get(Notebook, relation.target_notebook_id)
    if source is None or target is None or source.deleted_at or target.deleted_at:
        return None
    if source.course_id is None or target.course_id is None or source.course_id == target.course_id:
        return None
    source_course = db.get(Course, source.course_id)
    target_course = db.get(Course, target.course_id)
    if source_course is None or target_course is None or source_course.deleted_at or target_course.deleted_at:
        return None
    return {
        "id": relation.id,
        "source_course_id": source.course_id,
        "target_course_id": target.course_id,
        "source_notebook_id": source.id,
        "target_notebook_id": target.id,
        "source_title": source.title,
        "target_title": target.title,
        "source_course_name": source_course.name,
        "target_course_name": target_course.name,
        "relation_type": relation.relation_type,
        "reason": relation.description or "",
        "created_at": relation.created_at,
        "origin": relation.origin,
        "source_fingerprint": relation.source_fingerprint,
        "target_fingerprint": relation.target_fingerprint,
        "source_block_id": relation.source_block_id,
        "target_block_id": relation.target_block_id,
        "stale": any(
            block_id is not None and (
                (current := relation_anchor_fingerprint(book, block_id)) is None
                or current != saved
            )
            for book, block_id, saved in (
                (source, relation.source_block_id, relation.source_fingerprint),
                (target, relation.target_block_id, relation.target_fingerprint),
            )
        ),
    }


def relation_anchor_fingerprint(notebook: Notebook, block_id: str | None) -> str | None:
    if block_id is None:
        return None
    from app.notes.document import load_document
    from app.notes.index import build_sections

    stored = load_document(notebook.document_json)
    if stored.warning:
        return None
    section = next((row for row in build_sections(stored.content) if row.block_id == block_id), None)
    if section is None:
        return None
    return section_relation_fingerprint(section.heading, section.text)


def section_relation_fingerprint(heading: str, text: str) -> str:
    return hashlib.sha256(json.dumps(
        {"heading": heading, "text": text},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
