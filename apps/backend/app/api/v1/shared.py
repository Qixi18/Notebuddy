from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Conversation, Course, Material, Note
from app.services.resource_scopes import (
    require_conversation,
    require_course,
    require_material,
    require_note,
)


def ensure_conversation(db: Session, conversation_id: str) -> Conversation:
    return require_conversation(db, conversation_id)


def ensure_course(db: Session, course_id: str) -> Course:
    return require_course(db, course_id)


def ensure_material(db: Session, material_id: str) -> Material:
    return require_material(db, material_id)


def ensure_note(db: Session, note_id: str) -> Note:
    return require_note(db, note_id)
