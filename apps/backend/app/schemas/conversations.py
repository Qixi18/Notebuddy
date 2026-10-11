from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assistant import AssistantSource

TeacherPersonaId = Literal["elf", "doubao", "feiyu"]


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=300)
    default_scope: str = Field(default="course", pattern="^(course|material|page)$")


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    title: str
    default_scope: str
    created_at: datetime
    updated_at: datetime


class MessageEvidenceRead(BaseModel):
    id: str
    claim_key: str
    evidence_type: str
    support_level: str
    source_ref_id: str | None = None
    web_source_id: str | None = None
    snippet: str | None = None
    location_label: str | None = None


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    learning_goal: str | None
    status: str
    model_version: str | None
    failure_type: str | None
    created_at: datetime
    evidence: list[MessageEvidenceRead] = Field(default_factory=list)
    # 与 /assistant 直连回答保持同一套展示信息：回答模式标签 + 可点击的来源卡片。
    # 会话消息落库时只存了 evidence，这里在读取时从 evidence 反推，避免加表字段与迁移。
    mode: str = ""
    sources: list[AssistantSource] = Field(default_factory=list)


class ConversationMessageCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    learning_goal: str | None = Field(default=None, max_length=60)
    material_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    allow_web: bool = True
    idempotency_key: str | None = Field(default=None, max_length=120)
    # 本次回答使用哪一位 AI 教师的人设；未知取值由 app.ai.personas 回落到默认角色的做法保持一致
    teacher_persona: TeacherPersonaId = "elf"
