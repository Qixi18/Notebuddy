from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    course_id: str | None = None
    title: str
    tree_slot: int
    display_order: int
    order_revision: int
    is_default: bool
    created_at: datetime
    updated_at: datetime
    cover_url: str | None = None


UnboundNotebookSummary = NotebookSummary


class NotebookBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)


class NotebookTitleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class NotebookMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)


class NotebookRestoreDeletedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)


class DocumentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    type: Literal["h1", "h2", "p", "bullet"]
    text: str = Field(max_length=20000)


class NotebookDocumentUpdate(BaseModel):
    """Accepts the v2 document tree; the legacy ``blocks`` shape stays for a
    transition period so older tabs can still save simple notes."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int | None = None
    content: dict[str, Any] | None = None
    blocks: list[DocumentBlock] | None = None
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.schema_version is not None and self.schema_version != 2:
            raise ValueError("不支持的正文格式版本")
        if (self.content is None) == (self.blocks is None):
            raise ValueError("content 与 blocks 必须且只能提供一个")
        return self


class NotebookDocumentRead(BaseModel):
    schema_version: int = 2
    content: dict[str, Any]
    # Transitional projection for older clients; new clients must use content.
    blocks: list[DocumentBlock] = Field(default_factory=list)
    revision: int
    updated_at: datetime
    warning: str | None = None


class NotebookAttachmentRead(BaseModel):
    id: str
    url: str
    original_filename: str
    mime: str
    size_bytes: int
    created_at: datetime


class NotebookRevisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    revision: int
    origin: str
    created_at: datetime


class NotebookRevisionRead(NotebookRevisionSummary):
    schema_version: int
    content: dict[str, Any]


class NotebookRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


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
