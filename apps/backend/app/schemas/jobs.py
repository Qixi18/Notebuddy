from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    material_id: str
    kind: str
    status: str
    progress: int
    error_message: str | None
    phase: str
    web_search_status: str
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    attempt_count: int = 0
    completed_pages: int = 0
    total_pages: int = 0
