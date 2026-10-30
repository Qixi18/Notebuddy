from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    material_id: str | None
    source_node_id: str | None
    target_node_id: str | None
    kind: str
    candidate_name: str
    candidate_summary: str
    confidence: float
    rationale: str
    source_ids_json: str
    proposed_delta_json: str
    status: str
    model_version: str | None
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ProposalReview(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    note: str | None = Field(default=None, max_length=2000)
    # 逐块审查后的最终正文：confirm 时若提供则以其为准（部分采纳）；不提供沿用建议原文（旧行为不变）
    final_markdown: str | None = Field(default=None, max_length=20000)


class NoteSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    note_id: str
    proposed_markdown: str
    source_ids_json: str
    impact: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    # 来自 NoteSuggestion.note_title property：多目标建议卡与改动栏显示目标笔记标题
    note_title: str | None = None
