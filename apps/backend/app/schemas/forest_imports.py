from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Level = Literal["foundation", "professional", "application", "unspecified"]


class CurriculumRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    semester: int | None = Field(default=None, ge=1, le=30)
    level: Level = "unspecified"
    prerequisites: list[str] = Field(default_factory=list, max_length=30)
    source_label: str = Field(max_length=500)
    source_excerpt: str = Field(max_length=12000)
    existing_course_id: str | None = None

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


class CurriculumConfirm(BaseModel):
    rows: list[CurriculumRow] = Field(min_length=1, max_length=300)


class CurriculumImportRead(BaseModel):
    id: str
    status: Literal["pending", "processing", "preview", "confirmed", "failed"]
    filename: str | None
    mode: str | None
    warnings: list[str]
    rows: list[CurriculumRow]
    error_message: str | None
    job_id: str | None


class ForestJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: Literal["curriculum_import", "notebook_relations", "cross_course_relations", "validate_legacy_relations"]
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int
    error_message: str | None
