from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    knowledge_node_id: str
    material_id: str | None = None
    section_key: str | None = None
    section_order: int = 0
    title: str
    content_markdown: str
    content_origin: str
    user_locked: bool
    revision_number: int
    created_at: datetime
    updated_at: datetime



class NoteRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    note_id: str
    revision_number: int
    content_markdown: str
    content_origin: str
    user_locked: bool
    created_at: datetime



class NoteUpdate(BaseModel):
    content_markdown: str = Field(min_length=1, max_length=100000)
    expected_revision_number: int = Field(ge=1)
