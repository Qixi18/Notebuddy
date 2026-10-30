from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TeacherPersonaId = Literal["vodyanitsa"]


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    material_id: str | None = None
    asset_id: str | None = None
    page_number: int | None = None
    page_numbers: list[int] = Field(default_factory=list)
    document_block_ids: list[str] = Field(default_factory=list)
    allow_web: bool = True
    learning_goal: str | None = Field(default=None, max_length=60)
    teacher_persona: TeacherPersonaId = "vodyanitsa"


class AssistantSource(BaseModel):
    source_type: str = "course_material"
    source_ref_id: str | None = None
    material_id: str | None = None
    lecture_title: str | None = None
    page_number: int | None = None
    snippet: str
    title: str | None = None
    url: str | None = None
    site_name: str | None = None
    retrieved_at: datetime | None = None
    published_at: str | None = None
    location_label: str | None = None
    support_level: str = "direct"
    score_source: str | None = None
    notebook_id: str | None = None
    block_id: str | None = None
    document_block_id: str | None = None
    parse_run_id: str | None = None
    notebook_revision: int | None = None
    source_status: Literal["active", "stale", "unavailable"] = "active"


class AssistantClaim(BaseModel):
    claim_key: str
    evidence_type: str = "course_related"
    support_level: str = "related"
    source_indexes: list[int] = Field(default_factory=list)


class AssistantResponse(BaseModel):
    answer: str
    sources: list[AssistantSource]
    claims: list[AssistantClaim] = Field(default_factory=list)
    mode: str = "local-retrieval-preview"
    web_search_status: str = "unavailable"
