from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DocumentQualityRead(BaseModel):
    status: str
    score: float = 0.0
    pages_total: int = 0
    pages_ok: int = 0
    pages_empty: int = 0
    pages_failed: int = 0
    text_chars: int = 0
    text_chars_per_page: float = 0.0
    issues: list[dict[str, Any]] = []
    usable_page_ranges: list[list[int]] = []
    generation_allowed: bool = False
    generation_block_reason: str | None = None


class DocumentRunRead(BaseModel):
    id: str
    asset_id: str
    doc_type: str
    status: str
    parser_name: str
    parser_version: str
    config_version: str
    is_current: bool
    fingerprint: str
    page_count: int
    text_chars: int
    quality_status: str
    quality: DocumentQualityRead
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class DocumentPageRead(BaseModel):
    page_number: int
    status: str
    extraction: str
    width: float | None = None
    height: float | None = None
    rotation: int = 0
    confidence: float | None = None
    warnings: list[str] = []
    text_chars: int = 0
    render_url: str | None = None


class DocumentBlockRead(BaseModel):
    block_id: str
    page_number: int
    type: str
    level: int = 0
    text: str = ""
    latex: str | None = None
    table: dict[str, Any] | None = None
    figure: dict[str, Any] | None = None
    bbox: list[float] | None = None
    extraction: str
    confidence: float | None = None
    warnings: list[str] = []


class DocumentSectionRead(BaseModel):
    section_id: str
    title: str
    level: int
    page_start: int
    page_end: int
    block_ids: list[str] = []


class DocumentIRRead(BaseModel):
    run: DocumentRunRead
    pages: list[DocumentPageRead]
    sections: list[DocumentSectionRead]


class BlockCitationRead(BaseModel):
    notebook_id: str
    notebook_title: str
    block_id: str
    page_number: int
    quote: str
    status: str
