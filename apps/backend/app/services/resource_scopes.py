"""Shared resource scope checks for application use cases and HTTP adapters."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Conversation, Course, Material, Note, Notebook
from app.services.errors import ApplicationError


def require_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise ApplicationError(404, "课程不存在")
    return course


def require_material(db: Session, material_id: str) -> Material:
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is not None:
        raise ApplicationError(404, "资料不存在")
    return material


def require_note(db: Session, note_id: str) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise ApplicationError(404, "笔记不存在")
    require_course(db, note.course_id)
    return note


def require_notebook(
    db: Session, notebook_id: str, *, course_id: str | None = None,
    unbound: bool = False,
) -> Notebook:
    notebook = db.get(Notebook, notebook_id)
    if unbound and (notebook is None or notebook.deleted_at is not None
                    or notebook.course_id is not None):
        raise ApplicationError(404, "未绑定的笔记不存在")
    if notebook is None or notebook.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    if course_id is not None:
        require_course(db, course_id)
        if notebook.course_id != course_id:
            raise ApplicationError(404, "该课程中的笔记本不存在")
    return notebook


def require_conversation(db: Session, conversation_id: str) -> Conversation:
    from app.services.conversations import ConversationUnavailable, load_conversation

    try:
        return load_conversation(db, conversation_id)
    except ConversationUnavailable as exc:
        raise ApplicationError(404, exc.detail) from exc
