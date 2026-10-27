from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.assistant import AssistantSource

TeacherPersonaId = Literal["elf", "doubao", "feiyu"]


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=300)
    # 归属词表统一为 course / global / note。material、page 是旧词，等价于「整门课程」，
    # 仍接受但会被归一成 course，避免老客户端直接 422。
    default_scope: str = Field(default="course", pattern="^(course|global|note|material|page)$")
    scope: Literal["course", "global", "note"] | None = None
    # 仅在 scope='note' 时使用；存标题快照，笔记改名不回溯历史。
    note_id: str | None = Field(default=None, max_length=36)
    note_title: str | None = Field(default=None, max_length=300)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    title: str
    default_scope: str
    scope: str | None = None
    note_id: str | None = None
    note_title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationTitleUpdate(BaseModel):
    """重命名会话：仅改标题。手动改名后不会被首条问题的自动命名覆盖（自动命名只在标题仍为默认值时触发）。"""

    title: str = Field(min_length=1, max_length=300)

    @field_validator("title")
    @classmethod
    def _strip_and_reject_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空白")
        return stripped


class ConversationMessageHit(BaseModel):
    """课程内消息全文搜索的命中项（P6）：命中片段已按关键词截窗，前端负责高亮渲染。"""

    conversation_id: str
    conversation_title: str
    message_id: str
    message_role: str
    snippet: str
    created_at: datetime


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
    # agent 过程轨迹（思维链 + 工具步骤耗时），前端渲染成可展开的「过程」折叠块；无则为 None。
    process: dict | None = None
    # agent 产出建议（技能卡负载），随消息持久化；历史加载后卡片还原。
    suggestions: list[dict] | None = None
    # 首条问题触发后由后端回写的会话标题；前端据此刷新历史列表，避免仍显示「新对话」。
    conversation_title: str = "新对话"


class ConversationMessageCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    learning_goal: str | None = Field(default=None, max_length=60)
    material_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    allow_web: bool = True
    idempotency_key: str | None = Field(default=None, max_length=120)
    # 本次回答使用哪一位 AI 教师的人设；未知取值由 app.ai.personas 回落到默认角色的做法保持一致
    teacher_persona: TeacherPersonaId = "elf"
    # 会话归属：仅在会话尚无任何用户消息（首轮）时落库，之后忽略——范围是会话级属性。
    # 用于把答疑页自动建的「整门课程」空会话，在首轮改写成用户实际选择的范围。
    scope: Literal["course", "global", "note"] | None = None
    note_id: str | None = Field(default=None, max_length=36)
    note_title: str | None = Field(default=None, max_length=300)


class ReadingContext(BaseModel):
    """悬浮坞 agent 的阅读上下文：用户当前打开（或锁定）的笔记。"""

    note_id: str | None = None
    note_title: str | None = Field(default=None, max_length=300)
    section_title: str | None = Field(default=None, max_length=300)
    excerpt: str | None = Field(default=None, max_length=1200)


class NotebookDocumentContext(BaseModel):
    """整篇 Notebook 编辑器的上下文，与分节 Note 的 ReadingContext 互斥。"""

    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=36)
    notebook_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=0)
    title: str | None = Field(default=None, max_length=200)
    selection: str | None = Field(default=None, max_length=4000)
    excerpt: str | None = Field(default=None, max_length=2000)


class AgentMessageCreate(BaseModel):
    """悬浮坞 agent 提问（SSE 流式端点的请求体）。"""

    question: str = Field(min_length=1, max_length=2000)
    # note=锁定当前笔记 / course=整门课程 / global=跨课程全局可查（写建议仍只对打开的笔记）
    scope: Literal["note", "course", "global"] = "course"
    learning_goal: str | None = Field(default=None, max_length=60)
    material_id: str | None = None
    allow_web: bool = True
    idempotency_key: str | None = Field(default=None, max_length=120)
    teacher_persona: TeacherPersonaId = "elf"
    reading_context: ReadingContext | None = None
    notebook_context: NotebookDocumentContext | None = None
    # 发现开关（P4）：允许 agent 自主定位课程内任意笔记并对其提交修改建议。
    # 默认 False——悬浮坞不传即行为不变；答疑页传 True。同时是 kill switch。
    allow_note_discovery: bool = False
    # 出题开关（P10）：允许 agent 调 generate_quiz 出自测卷；同上，仅答疑页传 True。
    allow_quiz: bool = False
    # 学习模式（P9）：direct=直接答（默认）/ guided=引导式答疑（先诊断再提示，逐步展开）。
    # 消息级参数，不写会话；悬浮坞不传即行为不变。
    learning_mode: Literal["direct", "guided"] = "direct"

    @model_validator(mode="after")
    def _material_id_only_for_course_scope(self) -> "AgentMessageCreate":
        """课件收窄是「整门课程」档的消息级参数：global 语义矛盾、note 已是笔记级聚焦，携带即 422。"""
        if self.material_id and self.scope != "course":
            raise ValueError("material_id 仅在 scope='course' 时可用")
        return self
