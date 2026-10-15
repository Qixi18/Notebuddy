from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Note, NoteRevision


class NoteEditConflict(RuntimeError):
    """Raised when the browser is editing an outdated note revision."""


def update_note_as_user(
    db: Session,
    note: Note,
    content_markdown: str,
    expected_revision_number: int,
) -> Note:
    if note.revision_number != expected_revision_number:
        raise NoteEditConflict("笔记已经被更新，请重新读取后再保存")

    next_revision = note.revision_number + 1
    note.content_markdown = content_markdown.strip()
    note.content_origin = "user"
    note.user_locked = True
    note.revision_number = next_revision
    db.add(
        NoteRevision(
            note_id=note.id,
            revision_number=next_revision,
            content_markdown=note.content_markdown,
            content_origin="user",
            user_locked=True,
        )
    )
    from app.forest.jobs import enqueue_relations

    db.flush()
    enqueue_relations(db, note.course_id, note_ids=[note.id])
    db.commit()
    db.refresh(note)
    return note


def list_course_notes(db: Session, course_id: str) -> list[Note]:
    return list(
        db.scalars(
            select(Note).where(Note.course_id == course_id).order_by(Note.updated_at.desc())
        ).all()
    )
