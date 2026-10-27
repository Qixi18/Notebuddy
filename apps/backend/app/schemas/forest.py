"""Public contracts for forest profiles and Notebook-to-Notebook relations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ForestLevel = Literal["foundation", "professional", "application", "unspecified"]
LearningState = Literal["planned", "learning", "completed"]
RelationType = Literal["related", "prerequisite", "application"]


class ForestCourseRead(BaseModel):
    course_id: str
    name: str
    semester: int | None
    level: ForestLevel
    learning_state: LearningState
    position: int
    revision: int
    note_count: int          # number of Notebook body sections (kept for UI compatibility)
    material_count: int
    notebook_count: int = 0
    section_count: int = 0
    prerequisites: list[str]


class ForestRead(BaseModel):
    courses: list[ForestCourseRead]


class ForestSearchRead(BaseModel):
    course_id: str
    course_name: str
    notebook_id: str
    block_id: str | None = None
    title: str
    snippet: str = ""


class ForestCourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    semester: int | None = Field(default=None, ge=1, le=100)
    level: ForestLevel | None = None
    learning_state: LearningState | None = None
    position: int | None = None
    prerequisites: list[str] | None = Field(default=None, max_length=100)

    @field_validator("level", "learning_state", "position", "prerequisites")
    @classmethod
    def non_nullable_fields(cls, value):
        if value is None:
            raise ValueError("该字段不能为空")
        return value

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value):
        if value is None:
            return value
        cleaned = [name.strip() for name in value]
        if any(not name or len(name) > 200 for name in cleaned):
            raise ValueError("先修课程名称不能为空且不得超过200字符")
        return list(dict.fromkeys(cleaned))


class NotebookRelationRead(BaseModel):
    id: str
    source_course_id: str | None
    target_course_id: str | None
    source_notebook_id: str
    target_notebook_id: str
    source_title: str
    target_title: str
    source_course_name: str
    target_course_name: str
    relation_type: RelationType
    reason: str
    created_at: datetime
    source_block_id: str | None = None
    target_block_id: str | None = None
    stale: bool = False
    origin: Literal["manual", "ai"] = "manual"
    source_fingerprint: str | None = None
    target_fingerprint: str | None = None


class NotebookRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_notebook_id: str = Field(min_length=1, max_length=36)
    target_notebook_id: str = Field(min_length=1, max_length=36)
    relation_type: RelationType = "related"
    reason: str = Field(min_length=1, max_length=4000)
    source_block_id: str | None = Field(default=None, min_length=1, max_length=64)
    target_block_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写关联依据")
        return value.strip()
