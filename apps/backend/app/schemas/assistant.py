from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TeacherPersonaId = Literal["elf", "doubao", "feiyu"]


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    material_id: str | None = None
    page_number: int | None = None
    allow_web: bool = True
    learning_goal: str | None = Field(default=None, max_length=60)
    teacher_persona: TeacherPersonaId = "elf"


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
