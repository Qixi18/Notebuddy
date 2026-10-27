from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NotebookGenerationCreate(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100)


class NotebookGenerationApply(BaseModel):
    expected_revision: int = Field(ge=0)


class NotebookGenerationCandidateRead(BaseModel):
    id: str
    job_id: str
    notebook_id: str
    document: dict
    status: str
    created_at: datetime
    expires_at: datetime | None


class NotebookGenerationJobRead(BaseModel):
    id: str
    notebook_id: str
    status: str
    base_document_revision: int
    model: str
    prompt_version: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    generator: str | None = None
    parse_run_ids: list[str] = []
    plan: dict | None = None
    candidate: NotebookGenerationCandidateRead | None = None
