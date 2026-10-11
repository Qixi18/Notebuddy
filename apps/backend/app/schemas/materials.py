from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.jobs import JobRead


class MaterialRead(BaseModel):
    chapter_order: int = 0
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    lecture_title: str
    topic_title: str | None
    original_filename: str
    media_type: str | None
    size_bytes: int
    status: str
    page_count: int
    created_at: datetime
    parser_version: str | None = None
    document_warning: str | None = None
    deleted_at: datetime | None = None



class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    material_id: str
    page_number: int
    title: str | None
    raw_text: str
    parse_status: str
    warning: str | None
    location_type: str = "page"
    location_label: str | None = None
    stable_location_key: str | None = None
    extraction_method: str = "native_text"
    confidence: float | None = None


class BlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    page_id: str
    block_type: str
    content: str
    position: int
    font_size: float | None
    is_bold: bool
    object_id: str | None
    location_label: str | None
    extraction_method: str
    confidence: float | None
    warning: str | None
    note_ids: list[str] = []
    note_titles: list[str] = []


class PageEvidenceRead(PageRead):
    blocks: list[BlockRead] = []
    note_ids: list[str] = []
    note_titles: list[str] = []



class SourceRefRead(BaseModel):
    id: str
    page_block_id: str
    source_type: str
    quote: str
    material_id: str
    page_number: int
    location_type: str = "page"
    location_label: str | None = None
    status: str = "active"
    target_label: str | None = None



class UploadMaterialResponse(BaseModel):
    material: MaterialRead
    job: JobRead



class WebSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    url: str
    site_name: str
    snippet: str
    search_query: str
    score: float | None
    published_at: str | None
    retrieved_at: datetime
