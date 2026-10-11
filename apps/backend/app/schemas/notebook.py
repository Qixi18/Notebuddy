from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.notes import NoteRead


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    knowledge_node_id: str
    material_id: str | None
    section_key: str | None
    section_order: int
    title: str
    revision_number: int
    user_locked: bool
    updated_at: datetime


class ChapterRead(BaseModel):
    id: str
    title: str
    chapter_order: int
    status: str
    deleted_at: datetime | None
    sections: list[SectionRead]


class NotebookRead(BaseModel):
    course_id: str
    title: str
    order_revision: int
    chapters: list[ChapterRead]
    historical_sections: list[SectionRead]
    removed_chapters: list[ChapterRead]


class ChapterContentRead(BaseModel):
    material_id: str
    sections: list[NoteRead]


class NotebookOrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_ids: list[str] = Field(max_length=10000)
    expected_order_revision: int = Field(ge=0)
