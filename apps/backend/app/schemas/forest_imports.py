from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Level = Literal["foundation", "professional", "application", "unspecified"]


class CurriculumCourseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    course_code: str | None = Field(default=None, max_length=80)
    credits: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    hours: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    requirement: Literal['required', 'elective', 'unspecified'] = 'unspecified'
    semester: int | None = Field(default=None, ge=1, le=30)
    level: Level = "unspecified"
    prerequisites: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("课程名称不能为空")
        return value.strip()

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value: list[str]) -> list[str]:
        if any(not name.strip() or len(name) > 200 for name in value):
            raise ValueError("先修课程名称无效")
        return list(dict.fromkeys(name.strip() for name in value))

    @field_validator('course_code')
    @classmethod
    def clean_code(cls, value):
        return value.strip() or None if value is not None else None


class CurriculumRow(CurriculumCourseFields):
    key: str = Field(min_length=1, max_length=100)
    source_label: str = Field(max_length=500)
    source_excerpt: str = Field(max_length=12000)
    existing_course_id: str | None = None
    expected_profile_revision: int | None = Field(default=None, ge=0)


class CurriculumConfirm(BaseModel):
    rows: list[CurriculumRow] = Field(min_length=1, max_length=300)


class CurriculumImportRead(BaseModel):
    id: str
    status: Literal["pending", "processing", "preview", "confirmed", "failed", "reverted"]
    filename: str | None
    mode: str | None
    warnings: list[str]
    rows: list[CurriculumRow]
    error_message: str | None
    job_id: str | None
    progress: int = Field(default=0, ge=0, le=100)
    processing_route: Literal['standard', 'llm'] = 'standard'
    phase: str | None = None
    can_revert: bool = False


class ForestJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: Literal["curriculum_import", "notebook_relations", "cross_course_relations", "validate_legacy_relations"]
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int
    error_message: str | None
