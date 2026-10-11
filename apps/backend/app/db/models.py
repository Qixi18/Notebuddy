from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


note_source_refs = Table(
    "note_source_refs",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("source_ref_id", ForeignKey("source_refs.id", ondelete="CASCADE"), primary_key=True),
)

knowledge_node_source_refs = Table(
    "knowledge_node_source_refs",
    Base.metadata,
    Column(
        "knowledge_node_id",
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("source_ref_id", ForeignKey("source_refs.id", ondelete="CASCADE"), primary_key=True),
)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notebook_order_revision: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    # 除了 materials，其余关联表只有 course_id 外键。显式声明 ORM 级联，
    # 这样即使引擎未开启 SQLite 外键（tests / 迁移脚本 / 换库），
    # 删课程也不会留下孤儿知识点、笔记或检索块。
    materials: Mapped[list[Material]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    knowledge_proposals: Mapped[list[KnowledgeProposal]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    knowledge_changes: Mapped[list[KnowledgeChange]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    backup_records: Mapped[list[BackupRecord]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    knowledge_nodes: Mapped[list[KnowledgeNode]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    notes: Mapped[list[Note]] = relationship(back_populates="course", cascade="all, delete-orphan")
    knowledge_edges: Mapped[list[KnowledgeEdge]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    retrieval_chunks: Mapped[list[RetrievalChunk]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (Index("ix_materials_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    lecture_title: Mapped[str] = mapped_column(String(200), nullable=False)
    topic_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    page_count: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    chapter_order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    course: Mapped[Course] = relationship(back_populates="materials")
    pages: Mapped[list[MaterialPage]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_material_id", "material_id"),
        Index(
            "uq_processing_jobs_active_material",
            "material_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
        Index("uq_processing_jobs_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    web_search_status: Mapped[str] = mapped_column(String(30), default="not_started", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)

    material: Mapped[Material] = relationship(back_populates="jobs")


class MaterialPage(Base):
    __tablename__ = "material_pages"
    __table_args__ = (Index("ix_material_pages_material_id", "material_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parse_status: Mapped[str] = mapped_column(String(30), default="parsed", nullable=False)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_type: Mapped[str] = mapped_column(String(30), default="page", nullable=False)
    location_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stable_location_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(40), default="native_text", nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    material: Mapped[Material] = relationship(back_populates="pages")
    blocks: Mapped[list[PageBlock]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class PageBlock(Base):
    __tablename__ = "page_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    page_id: Mapped[str] = mapped_column(ForeignKey("material_pages.id", ondelete="CASCADE"))
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)
    font_size: Mapped[float | None] = mapped_column(nullable=True)
    is_bold: Mapped[bool] = mapped_column(default=False, nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(40), default="native_text", nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    page: Mapped[MaterialPage] = relationship(back_populates="blocks")
    source_refs: Mapped[list[SourceRef]] = relationship(
        back_populates="page_block", cascade="all, delete-orphan"
    )
    retrieval_chunk: Mapped[RetrievalChunk | None] = relationship(
        back_populates="page_block", uselist=False, cascade="all, delete-orphan"
    )


class SourceRef(Base):
    __tablename__ = "source_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    page_block_id: Mapped[str] = mapped_column(ForeignKey("page_blocks.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(40), default="course_material", nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    target_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    page_block: Mapped[PageBlock] = relationship(back_populates="source_refs")
    notes: Mapped[list[Note]] = relationship(
        secondary=note_source_refs, back_populates="source_refs"
    )
    knowledge_nodes: Mapped[list[KnowledgeNode]] = relationship(
        secondary=knowledge_node_source_refs, back_populates="source_refs"
    )


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_knowledge_nodes_course_name"),
        Index("ix_knowledge_nodes_course_id", "course_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="knowledge_nodes")
    notes: Mapped[list[Note]] = relationship(back_populates="knowledge_node")
    source_refs: Mapped[list[SourceRef]] = relationship(
        secondary=knowledge_node_source_refs, back_populates="knowledge_nodes"
    )
    outgoing_edges: Mapped[list[KnowledgeEdge]] = relationship(
        foreign_keys="KnowledgeEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list[KnowledgeEdge]] = relationship(
        foreign_keys="KnowledgeEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "relation_type",
            name="uq_knowledge_edges_relation",
        ),
        Index("ix_knowledge_edges_course_id", "course_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE")
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String(30), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="knowledge_edges")
    source_node: Mapped[KnowledgeNode] = relationship(
        foreign_keys=[source_node_id], back_populates="outgoing_edges"
    )
    target_node: Mapped[KnowledgeNode] = relationship(
        foreign_keys=[target_node_id], back_populates="incoming_edges"
    )


class WebSource(Base):
    __tablename__ = "web_sources"
    __table_args__ = (Index("ix_web_sources_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), nullable=True)
    knowledge_node_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    search_query: Mapped[str] = mapped_column(String(1000), nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_course_id", "course_id"),
        UniqueConstraint("material_id", "section_key", name="uq_notes_material_section"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    knowledge_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE")
    )
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), nullable=True)
    section_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    section_order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_origin: Mapped[str] = mapped_column(String(30), default="ai", nullable=False)
    user_locked: Mapped[bool] = mapped_column(default=False, nullable=False)
    revision_number: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="notes")
    knowledge_node: Mapped[KnowledgeNode] = relationship(back_populates="notes")
    revisions: Mapped[list[NoteRevision]] = relationship(
        back_populates="note", cascade="all, delete-orphan", order_by="NoteRevision.revision_number"
    )
    source_refs: Mapped[list[SourceRef]] = relationship(
        secondary=note_source_refs, back_populates="notes"
    )


class NoteRevision(Base):
    __tablename__ = "note_revisions"
    __table_args__ = (Index("ix_note_revisions_note_id", "note_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_origin: Mapped[str] = mapped_column(String(30), nullable=False)
    user_locked: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    note: Mapped[Note] = relationship(back_populates="revisions")


class NoteSourceMapping(Base):
    __tablename__ = "note_source_mappings"
    __table_args__ = (Index("ix_note_source_mappings_note_id", "note_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    source_ref_id: Mapped[str] = mapped_column(ForeignKey("source_refs.id", ondelete="CASCADE"))
    fragment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    citation_type: Mapped[str] = mapped_column(String(40), default="whole_note", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    note: Mapped[Note] = relationship()
    source_ref: Mapped[SourceRef] = relationship()


class RetrievalChunk(Base):
    __tablename__ = "retrieval_chunks"
    __table_args__ = (Index("ix_retrieval_chunks_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    page_block_id: Mapped[str] = mapped_column(
        ForeignKey("page_blocks.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="retrieval_chunks")
    page_block: Mapped[PageBlock] = relationship(back_populates="retrieval_chunk")


class Conversation(Base):
    """Persisted, course-scoped assistant conversation."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300), default="新对话", nullable=False)
    default_scope: Mapped[str] = mapped_column(String(30), default="course", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="conversations")
    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conversation_id", "conversation_id"),
        UniqueConstraint("conversation_id", "idempotency_key", name="uq_message_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    learning_goal: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    evidence: Mapped[list[MessageEvidence]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageEvidence(Base):
    __tablename__ = "message_evidence"
    __table_args__ = (Index("ix_message_evidence_message_id", "message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey("conversation_messages.id", ondelete="CASCADE"))
    source_ref_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_refs.id", ondelete="CASCADE"), nullable=True
    )
    web_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("web_sources.id", ondelete="CASCADE"), nullable=True
    )
    claim_key: Mapped[str] = mapped_column(String(200), default="answer", nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(40), default="course_direct", nullable=False)
    support_level: Mapped[str] = mapped_column(String(30), default="direct", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    message: Mapped[ConversationMessage] = relationship(back_populates="evidence")
    source_ref: Mapped[SourceRef | None] = relationship()
    web_source: Mapped[WebSource | None] = relationship()


class KnowledgeProposal(Base):
    __tablename__ = "knowledge_proposals"
    __table_args__ = (Index("ix_knowledge_proposals_course_status", "course_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    material_id: Mapped[str | None] = mapped_column(
        ForeignKey("materials.id", ondelete="SET NULL"), nullable=True
    )
    source_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    target_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    candidate_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    proposed_delta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    course: Mapped[Course] = relationship(back_populates="knowledge_proposals")
    source_node: Mapped[KnowledgeNode | None] = relationship(foreign_keys=[source_node_id])
    target_node: Mapped[KnowledgeNode | None] = relationship(foreign_keys=[target_node_id])


class KnowledgeChange(Base):
    __tablename__ = "knowledge_changes"
    __table_args__ = (Index("ix_knowledge_changes_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    after_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="knowledge_changes")


class NoteSuggestion(Base):
    __tablename__ = "note_suggestions"
    __table_args__ = (Index("ix_note_suggestions_note_status", "note_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    proposed_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    impact: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    note: Mapped[Note] = relationship()


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_course_status", "course_id", "status"),
        UniqueConstraint("course_id", "target_type", "target_id", "category", name="uq_feedback_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    course: Mapped[Course] = relationship(back_populates="feedback")


class BackupRecord(Base):
    __tablename__ = "backup_records"
    __table_args__ = (Index("ix_backup_records_course_id", "course_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    course: Mapped[Course | None] = relationship(back_populates="backup_records")


class ProviderCall(Base):
    """Redacted audit record for an optional external provider call."""

    __tablename__ = "provider_calls"
    __table_args__ = (
        Index("ix_provider_calls_provider_created", "provider", "created_at"),
        Index("ix_provider_calls_course_created", "course_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    material_id: Mapped[str | None] = mapped_column(
        ForeignKey("materials.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_units: Mapped[int | None] = mapped_column(nullable=True)
    response_units: Mapped[int | None] = mapped_column(nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
