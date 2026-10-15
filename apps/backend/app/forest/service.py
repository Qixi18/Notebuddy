"""Forest domain rules without modifying course notes or legacy graph edges."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db.models import (
    Course,
    CrossCourseRelation,
    ForestCourseProfile,
    Material,
    MaterialPage,
    Note,
    PageBlock,
    SourceRef,
    note_source_refs,
)


class ForestConflict(ValueError):
    pass


def _json_strings(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []


def ensure_profile(db: Session, course: Course) -> ForestCourseProfile:
    """Initialize once; a later upload never changes a user's learning state."""
    profile = db.get(ForestCourseProfile, course.id)
    if profile is not None:
        return profile
    last_position = db.scalar(select(func.max(ForestCourseProfile.position)))
    position = int(last_position) + 1 if last_position is not None else 0
    has_material = (
        db.scalar(
            select(Material.id)
            .where(Material.course_id == course.id, Material.deleted_at.is_(None))
            .limit(1)
        )
        is not None
    )
    db.execute(
        insert(ForestCourseProfile)
        .values(
            course_id=course.id,
            position=position,
            learning_state="learning" if has_material else "planned",
        )
        .on_conflict_do_nothing(index_elements=[ForestCourseProfile.course_id])
    )
    return db.get(ForestCourseProfile, course.id, populate_existing=True)


def _historical_material_exists(*, active: bool):
    query = (
        select(1)
        .select_from(note_source_refs)
        .join(SourceRef, SourceRef.id == note_source_refs.c.source_ref_id)
        .join(PageBlock, PageBlock.id == SourceRef.page_block_id)
        .join(MaterialPage, MaterialPage.id == PageBlock.page_id)
        .join(Material, Material.id == MaterialPage.material_id)
        .where(note_source_refs.c.note_id == Note.id, Material.course_id == Note.course_id)
    )
    if active:
        query = query.where(Material.deleted_at.is_(None))
    return exists(query)


def visible_note_predicate():
    """Exclude removed lectures, including pre-notebook historical references."""
    direct_material = exists(
        select(1).where(
            Material.id == Note.material_id,
            Material.course_id == Note.course_id,
            Material.deleted_at.is_(None),
        )
    )
    return or_(
        direct_material,
        (
            Note.material_id.is_(None)
            & (
                ~_historical_material_exists(active=False)
                | _historical_material_exists(active=True)
            )
        ),
    )


def note_is_visible(db: Session, note: Note) -> bool:
    return (
        db.scalar(
            select(Note.id)
            .join(Course, Course.id == Note.course_id)
            .where(Note.id == note.id, Course.deleted_at.is_(None), visible_note_predicate())
        )
        is not None
    )


def active_note_sources(db: Session, note: Note) -> list[SourceRef]:
    """Return only linked, current, same-course quotes verifiable in a real block."""
    query = (
        select(SourceRef, PageBlock.content)
        .join(note_source_refs, note_source_refs.c.source_ref_id == SourceRef.id)
        .join(PageBlock, PageBlock.id == SourceRef.page_block_id)
        .join(MaterialPage, MaterialPage.id == PageBlock.page_id)
        .join(Material, Material.id == MaterialPage.material_id)
        .where(
            note_source_refs.c.note_id == note.id,
            SourceRef.status == "active",
            SourceRef.source_type == "course_material",
            MaterialPage.is_active.is_(True),
            Material.course_id == note.course_id,
            Material.deleted_at.is_(None),
        )
    )
    if note.material_id is not None:
        query = query.where(Material.id == note.material_id)
    result = []
    for ref, content in db.execute(query.order_by(SourceRef.id)).all():
        quote = " ".join(ref.quote.split())
        if quote and quote in " ".join(content.split()):
            result.append(ref)
    return result


def evidence_fingerprint(db: Session, note: Note, ref_ids: list[str] | None = None) -> str:
    """Include source content and parse identity without changing protected note revisions."""
    rows = [
        [ref.id, ref.quote, ref.page_block_id, ref.parser_version,
         ref.page_block.content, ref.page_block.page.id, ref.page_block.page.stable_location_key]
        for ref in active_note_sources(db, note)
        if ref_ids is None or ref.id in ref_ids
    ]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def relation_fingerprint(db: Session, source: Note, target: Note,
                         source_ids: list[str], target_ids: list[str]) -> str:
    return hashlib.sha256((evidence_fingerprint(db, source, source_ids)
                           + evidence_fingerprint(db, target, target_ids)).encode()).hexdigest()


def list_forest_courses(db: Session) -> list[dict]:
    courses = list(
        db.scalars(
            select(Course).where(Course.deleted_at.is_(None)).order_by(Course.created_at, Course.id)
        ).all()
    )
    material_counts = dict(
        db.execute(
            select(Material.course_id, func.count())
            .where(Material.deleted_at.is_(None))
            .group_by(Material.course_id)
        ).all()
    )
    note_counts = dict(
        db.execute(
            select(Note.course_id, func.count())
            .where(visible_note_predicate())
            .group_by(Note.course_id)
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
                "note_count": note_counts.get(course.id, 0),
                "material_count": material_counts.get(course.id, 0),
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
    updated = db.execute(
        update(ForestCourseProfile)
        .where(
            ForestCourseProfile.course_id == course.id,
            ForestCourseProfile.revision == expected_revision,
        )
        .values(**values)
    )
    if updated.rowcount != 1:
        raise ForestConflict("森林课程信息已被修改，请刷新后重试")


def relation_display(db: Session, relation: CrossCourseRelation) -> dict | None:
    source, target = db.get(Note, relation.source_note_id), db.get(Note, relation.target_note_id)
    if (
        source is None
        or target is None
        or not note_is_visible(db, source)
        or not note_is_visible(db, target)
    ):
        return None
    source_course, target_course = (
        db.get(Course, source.course_id),
        db.get(Course, target.course_id),
    )
    source_ids, target_ids = (
        _json_strings(relation.source_ref_ids_json),
        _json_strings(relation.target_ref_ids_json),
    )
    current_source_ids = {ref.id for ref in active_note_sources(db, source)}
    current_target_ids = {ref.id for ref in active_note_sources(db, target)}
    stale = (
        source.course_id != relation.source_course_id
        or target.course_id != relation.target_course_id
        or source.course_id == target.course_id
        or source.revision_number != relation.source_revision
        or target.revision_number != relation.target_revision
        or not source_ids
        or not target_ids
        or not set(source_ids).issubset(current_source_ids)
        or not set(target_ids).issubset(current_target_ids)
        or (relation.evidence_fingerprint is not None and relation.evidence_fingerprint
            != relation_fingerprint(db, source, target, source_ids, target_ids))
    )
    return {
        "id": relation.id,
        "source_course_id": source.course_id,
        "target_course_id": target.course_id,
        "source_note_id": source.id,
        "target_note_id": target.id,
        "source_title": source.title,
        "target_title": target.title,
        "source_course_name": source_course.name,
        "target_course_name": target_course.name,
        "relation_type": relation.relation_type,
        "reason": relation.reason,
        "status": relation.status,
        "origin": relation.origin,
        "activation_mode": relation.activation_mode or (
            "manual" if relation.status == "confirmed" else None),
        "evidence_fingerprint": relation.evidence_fingerprint,
        "source_revision": relation.source_revision,
        "target_revision": relation.target_revision,
        "stale": stale,
        "source_ref_ids": source_ids,
        "target_ref_ids": target_ids,
    }
