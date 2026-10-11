from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)



class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    deleted_at: datetime | None = None



class DeletionPreview(BaseModel):
    course_id: str
    material_id: str | None
    materials: int
    pages: int
    source_refs: int
    knowledge_nodes_touched: int
    user_notes_protected: int
    original_bytes: int
    active_jobs: int
    action: str
