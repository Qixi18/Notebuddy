from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    name: str
    summary: str | None
    status: str



class KnowledgeNodeSourceRead(BaseModel):
    material_id: str
    lecture_title: str
    topic_title: str | None = None
    page_number: int



class KnowledgeNodeWithSourcesRead(KnowledgeNodeRead):
    sources: list[KnowledgeNodeSourceRead] = []



class KnowledgeEdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    confidence: float | None
    created_by: str



class KnowledgeGraphRead(BaseModel):
    nodes: list[KnowledgeNodeWithSourcesRead]
    edges: list[KnowledgeEdgeRead]
    occurrences: list[dict] = []


class KnowledgeChangeRead(BaseModel):
    id: str
    proposal_id: str | None
    node_id: str | None
    change_type: str
    before_json: str
    after_json: str
    reason: str
    created_at: datetime
