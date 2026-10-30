from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AssetRead(BaseModel):
    processing_route: str = 'standard'
    id: str
    source_type: str
    media_type: str
    mime_type: str
    original_name: str
    byte_size: int
    sha256: str | None
    state: str
    role: str
    content_url: str
    created_at: datetime


class AssetProcessingJobRead(BaseModel):
    phase: str = 'parse'
    completed_pages: int = 0
    total_pages: int = 0
    id: str
    asset_id: str
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class AssetUploadRead(BaseModel):
    asset: AssetRead
    processing_job: AssetProcessingJobRead | None = None
    upload_batch_id: str | None = None
