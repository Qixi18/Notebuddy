from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Conversation, Course, Material, Note
from app.services.conversations import ConversationUnavailable, load_conversation


def ensure_conversation(db: Session, conversation_id: str) -> Conversation:
    try:
        return load_conversation(db, conversation_id)
    except ConversationUnavailable as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc


def ensure_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def ensure_material(db: Session, material_id: str) -> Material:
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is not None:
        raise HTTPException(status_code=404, detail="资料不存在")
    ensure_course(db, material.course_id)
    return material


def ensure_note(db: Session, note_id: str) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    ensure_course(db, note.course_id)
    return note
