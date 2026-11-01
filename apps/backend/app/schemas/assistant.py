from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from app.ai.personas import DEFAULT_PERSONA_ID, PERSONA_IDS


def _normalize_teacher_persona(value: object) -> object:
    # Historical clients may still send the retired persona IDs.
    if value in ("elf", "doubao", "feiyu"):
        return DEFAULT_PERSONA_ID
    return value


# 人设取值与 app.ai.personas 同源（人设表是唯一事实源），叠加历史角色 ID 的兼容归一化：
# 之前 Literal 硬编码旧三元组而 personas 已只剩 vodyanitsa，导致所有提问 422。
TeacherPersonaId = Annotated[
    Literal[tuple(PERSONA_IDS)], BeforeValidator(_normalize_teacher_persona)
]
DEFAULT_TEACHER_PERSONA = DEFAULT_PERSONA_ID


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
