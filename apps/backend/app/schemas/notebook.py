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


class NotebookRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_notebook_id: str = Field(min_length=1, max_length=36)
    relation_type: str = Field(default="related", min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)


class NotebookRelationRead(BaseModel):
    id: str
    source_notebook_id: str
    target_notebook_id: str
    related_notebook_id: str
    related_notebook_title: str
    direction: Literal["outgoing", "incoming"]
    relation_type: str
    description: str | None
    created_at: datetime


class NotebookMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)


class NotebookBulkManageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notebook_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["move", "delete"]
    course_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_target(self):
        if self.action == "move" and self.course_id == "":
            raise ValueError("目标课程无效")
        if len(set(self.notebook_ids)) != len(self.notebook_ids):
            raise ValueError("笔记列表包含重复项目")
        return self


class NotebookRestoreDeletedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str | None = Field(default=None, min_length=1, max_length=36)


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


class BlockSourceRead(BaseModel):
    block_id: str
    document_block_id: str
    parse_run_id: str
    parse_version: str | None = None
    asset_id: str
    asset_name: str
    page_number: int
    location_label: str
    quote: str
    block_type: str
    confidence: float | None = None
    status: str
    generation_job_id: str | None = None


class NotebookEditSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    notebook_id: str
    notebook_title: str | None = None
    base_revision: int
    rationale: str
    operations: list[dict[str, Any]] = Field(default_factory=list)
    proposed_content: dict[str, Any] | None = None
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None


class NotebookEditSuggestionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject"]
    expected_revision: int = Field(ge=0)
    selected_operation_indices: list[int] | None = Field(default=None, max_length=8)


class NotebookEditSuggestionBatchReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_ids: list[str] = Field(min_length=1, max_length=200)


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
    processing: bool = False
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
    block_id: str | None = Field(default=None, max_length=64)
    mode: Literal["chapter", "book"]
    section_offset: float = Field(ge=0, le=1)
    expected_revision: int = Field(ge=0)


class ReadingPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notebook_id: str
    chapter_id: str | None
    note_id: str | None
    block_id: str | None = None
    mode: Literal["chapter", "book"]
    section_offset: float
    revision: int
    updated_at: datetime


class CourseTreeRead(BaseModel):
    course_id: str
    notebooks: list[NotebookRead]
