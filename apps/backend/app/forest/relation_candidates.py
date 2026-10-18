"""Read eligible notes and their evidence snapshots for relation jobs.

This module only queries the caller's session. The job coordinator owns writes,
transaction boundaries, retries, and relation validation.
"""

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, load_only

from app.db.models import Course, Material, Note
from app.forest.service import active_note_sources, evidence_fingerprint


def live_note_query(course_id: str | None = None):
    query = (
        select(Note)
        .join(Course, Note.course_id == Course.id)
        .outerjoin(Material, Note.material_id == Material.id)
        .where(
            Course.deleted_at.is_(None),
            or_(Note.material_id.is_(None), Material.deleted_at.is_(None)),
        )
    )
    return query.where(Note.course_id == course_id) if course_id else query


def source_snapshot(
    db: Session,
    course_id: str,
    *,
    material_id: str | None = None,
    note_ids: list[str] | None = None,
) -> list[dict]:
    query = live_note_query(course_id).options(
        load_only(Note.id, Note.course_id, Note.material_id, Note.revision_number)
    ).order_by(Note.id)
    if material_id is not None:
        query = query.where(Note.material_id == material_id)
    if note_ids is not None:
        query = query.where(Note.id.in_(note_ids))
    return [
        {
            "note_id": note.id,
            "revision": note.revision_number,
            "evidence": evidence_fingerprint(db, note),
        }
        for note in db.scalars(query)
    ]


def _tokens(title: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9]+", title.lower()))
    chinese = re.findall(r"[\u4e00-\u9fff]+", title)
    words.update(
        group[index : index + 2] for group in chinese for index in range(max(1, len(group) - 1))
    )
    return words


def _note_snapshot(db: Session, note: Note) -> dict | None:
    refs = active_note_sources(db, note)
    if not refs:
        return None
    return {
        "note_id": note.id,
        "course_id": note.course_id,
        "course_name": note.course.name,
        "title": note.title,
        "revision": note.revision_number,
        "fingerprint": evidence_fingerprint(db, note),
        "evidence": [
            {
                "ref_id": source.id,
                "quote": source.quote[:600],
                "location": source.target_label
                or source.page_block.location_label
                or source.page_block.page.location_label,
            }
            for source in refs[:3]
        ],
    }


def candidate_snapshots(db: Session, course_id: str, source_ids: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    # Rank all lightweight titles before applying evidence/prompt budgets. Taking
    # the newest rows first permanently hid older prerequisite material.
    own_metadata = list(
        db.execute(
            live_note_query(course_id).where(Note.id.in_(source_ids) if source_ids is not None else True)
            .with_only_columns(Note.id, Note.title, Note.course_id)
        ).all()
    )
    metadata = list(
        db.execute(
            live_note_query()
            .where(Note.course_id != course_id)
            .with_only_columns(Note.id, Note.title, Note.course_id)
        ).all()
    )
    other_titles = {row.title.casefold() for row in metadata}
    other_terms = set().union(*(_tokens(row.title) for row in metadata)) if metadata else set()
    own_metadata.sort(
        key=lambda row: (
            -int(row.title.casefold() in other_titles),
            -len(other_terms & _tokens(row.title)),
            row.id,
        )
    )

    # Even selected note objects defer the body: only titles, versions and
    # verified source excerpts are needed by this candidate analysis.
    def load_snapshot(note_id: str):
        note = db.scalar(
            select(Note)
            .where(Note.id == note_id)
            .options(
                load_only(
                    Note.id,
                    Note.course_id,
                    Note.material_id,
                    Note.title,
                    Note.revision_number,
                )
            )
        )
        return _note_snapshot(db, note)

    source = []
    for row in own_metadata:
        snapshot = load_snapshot(row.id)
        if snapshot:
            source.append(snapshot)
        if len(source) == 30:
            break
    terms = set().union(*(_tokens(item["title"]) for item in source)) if source else set()
    source_titles = {item["title"].casefold() for item in source}
    metadata.sort(
        key=lambda row: (
            -int(row.title.casefold() in source_titles),
            -len(terms & _tokens(row.title)),
            row.id,
        )
    )
    target = []
    for row in metadata:
        snapshot = load_snapshot(row.id)
        if snapshot:
            target.append(snapshot)
        if len(target) == 18:
            break
    return source, target
