from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.notes import NoteRead


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    notebook_id: str
    tree_slot: int
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


class NotebookSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    course_id: str
    title: str
    tree_slot: int
    display_order: int
    order_revision: int
    is_default: bool
    created_at: datetime
    updated_at: datetime


class UnboundNotebookSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    course_id: str | None = None
    title: str
    tree_slot: int | None = None
    display_order: int = 0
    order_revision: int = 0
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class NotebookBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)


class NotebookTitleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class DocumentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    type: Literal["h1", "h2", "p", "bullet"]
    text: str = Field(max_length=20000)


class NotebookDocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[DocumentBlock] = Field(max_length=3000)
    expected_revision: int = Field(ge=0)


class NotebookDocumentRead(BaseModel):
    blocks: list[DocumentBlock]
    revision: int
    updated_at: datetime


class NotebookRead(BaseModel):
    id: str
    course_id: str
    title: str
    tree_slot: int
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


class ReadingPositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_id: str | None = None
    note_id: str | None = None
    mode: Literal["chapter", "book"]
    section_offset: float = Field(ge=0, le=1)
    expected_revision: int = Field(ge=0)


class ReadingPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notebook_id: str
    chapter_id: str | None
    note_id: str | None
    mode: Literal["chapter", "book"]
    section_offset: float
    revision: int
    updated_at: datetime


class CourseTreeRead(BaseModel):
    course_id: str
    notebooks: list[NotebookRead]
