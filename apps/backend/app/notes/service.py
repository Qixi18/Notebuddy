"""Legacy Note bodies are read-only evidence after migration.

The only supported editable body is ``Notebook.document_json``.  These helpers
exist for audits/migration reports and must not be used by new write paths.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Note


class NoteEditRetired(RuntimeError):
    """Raised when legacy code tries to write ``Note.content_markdown``."""


def update_note_as_user(*_args, **_kwargs) -> Note:
    raise NoteEditRetired(
        "旧 Note 正文写入已退役：学习笔记正文只写入 Notebook.document_json"
    )


def list_course_notes(db: Session, course_id: str) -> list[Note]:
    """Read-only legacy listing for migration/audit screens."""
    return list(
        db.scalars(
            select(Note).where(Note.course_id == course_id).order_by(Note.updated_at.desc())
        ).all()
    )
