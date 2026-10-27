from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.forest_models import (
    CrossCourseRelation,  # noqa: F401 - compatibility exports
    CurriculumImport,  # noqa: F401 - compatibility exports
    ForestCourseProfile,  # noqa: F401 - compatibility exports
    ForestJob,  # noqa: F401 - compatibility exports
)
from app.db.model_utils import new_id, utc_now

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
    last_opened_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notebooks: Mapped[list[Notebook]] = relationship(passive_deletes=True)
    materials: Mapped[list[Material]] = relationship(back_populates="course", passive_deletes=True)

    # 课程数据显式声明 ORM 级联，
    # 这样即使引擎未开启 SQLite 外键（tests / 迁移脚本 / 换库），
    # 删课程也不会留下孤儿知识点、笔记或检索块。
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


class Notebook(Base):
    __tablename__ = "notebooks"
    __table_args__ = (
        UniqueConstraint("course_id", "tree_slot", name="uq_notebooks_course_slot"),
        Index("uq_notebooks_default", "course_id", unique=True, sqlite_where=text("is_default = 1")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(default=0, server_default="0")
    order_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    document_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    document_revision: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    cover_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cover_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, server_default="0")
    tree_slot: Mapped[int] = mapped_column(nullable=False)
    next_note_slot: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    reading_position: Mapped[NotebookReadingPosition | None] = relationship(cascade="all, delete-orphan")
    materials: Mapped[list[Material]] = relationship(back_populates="notebook", cascade="all, delete-orphan")
    attachments: Mapped[list[NotebookAttachment]] = relationship(back_populates="notebook", cascade="all, delete-orphan")
    outgoing_links: Mapped[list[NotebookRelation]] = relationship(
        foreign_keys="NotebookRelation.source_notebook_id",
        back_populates="source_notebook", cascade="all, delete-orphan",
    )
    incoming_links: Mapped[list[NotebookRelation]] = relationship(
        foreign_keys="NotebookRelation.target_notebook_id",
        back_populates="target_notebook", cascade="all, delete-orphan",
    )


class NotebookRelation(Base):
    """An explicit, typed link between two independently stored notebooks."""

    __tablename__ = "notebook_relations"
    __table_args__ = (
        CheckConstraint("source_notebook_id <> target_notebook_id", name="ck_notebook_relations_no_self_link"),
        Index("uq_notebook_relations_endpoints_anchors", "source_notebook_id", "target_notebook_id",
              "relation_type", text("coalesce(source_block_id, '')"),
              text("coalesce(target_block_id, '')"), unique=True),
        Index("ix_notebook_relations_target", "target_notebook_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False,
    )
    target_notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False, default="related")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    source_notebook: Mapped[Notebook] = relationship(
        foreign_keys=[source_notebook_id], back_populates="outgoing_links",
    )
    target_notebook: Mapped[Notebook] = relationship(
        foreign_keys=[target_notebook_id], back_populates="incoming_links",
    )


class NotebookReadingPosition(Base):
    __tablename__ = "notebook_reading_positions"
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # New reading target: a stable block in document_json (note_id stays for
    # legacy rows until the old Note path is dropped).
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    section_offset: Mapped[float] = mapped_column(default=0)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class NotebookDocumentRevision(Base):
    """Immutable snapshots of a notebook document, written with each save."""

    __tablename__ = "notebook_document_revisions"
    __table_args__ = (
        UniqueConstraint("notebook_id", "revision", name="uq_notebook_document_revisions"),
        UniqueConstraint("id", "notebook_id", name="uq_notebook_revision_id_notebook"),
        Index("ix_notebook_document_revisions_notebook", "notebook_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(nullable=False)
    schema_version: Mapped[int] = mapped_column(default=2, server_default="2", nullable=False)
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="autosave", server_default="autosave")
    # Migrated legacy history keeps its original timestamp and is never trimmed
    # by the rolling autosave retention policy.
    legacy_created_at: Mapped[datetime | None] = mapped_column(nullable=True)
    retention: Mapped[str] = mapped_column(
        String(20), default="rolling", server_default="rolling", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NotebookAttachment(Base):
    """Image (or other) attachment owned by one notebook document."""

    __tablename__ = "notebook_attachments"
    __table_args__ = (
        Index("ix_notebook_attachments_notebook", "notebook_id"),
        UniqueConstraint("asset_id", name="uq_notebook_attachments_asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"))
    # Legacy course scope retained until historical rows are reconciled.
    # New uploads derive course context from Notebook and leave this NULL.
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    notebook: Mapped[Notebook] = relationship(back_populates="attachments")


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index("ix_materials_course_id", "course_id"),
        UniqueConstraint("asset_id", name="uq_materials_asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Nullable during the legacy course-material compatibility period. New
    # Notebook uploads always set notebook_id; legacy course-only rows remain
    # queryable without being assigned to an arbitrary Notebook.
    notebook_id: Mapped[str | None] = mapped_column(ForeignKey("notebooks.id", ondelete="SET NULL"), nullable=True, index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
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

    notebook: Mapped[Notebook | None] = relationship(back_populates="materials")
    course: Mapped[Course | None] = relationship(back_populates="materials")
    pages: Mapped[list[MaterialPage]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )



class NotebookUploadBatch(Base):
    """Durable grouping and close marker for source uploads."""

    __tablename__ = "notebook_upload_batches"
    __table_args__ = (Index("ix_notebook_upload_batches_notebook", "notebook_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotebookGenerationInput(Base):
    """Per-Asset idempotency and recovery state; generation snapshots remain on the job."""

    __tablename__ = "notebook_generation_inputs"
    __table_args__ = (
        Index("ix_notebook_generation_inputs_batch_state", "batch_id", "status", "created_at"),
        Index("ix_notebook_generation_inputs_status", "status", "updated_at"),
        CheckConstraint(
            "status IN ('waiting_parse','parsing','parse_failed','ready','generating',"
            "'generation_failed','completed')",
            name="ck_notebook_generation_input_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, unique=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("notebook_upload_batches.id", ondelete="CASCADE"), nullable=False)
    parse_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    parse_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parse_result_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_generation_jobs.id", ondelete="SET NULL"), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="waiting_parse")
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Asset(Base):
    """Stable metadata for a file owned by one Notebook or a legacy record."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_state_created", "state", "created_at"),
        Index("ix_assets_sha256", "sha256"),
        CheckConstraint(
            "state IN ('staging','ready','missing','quarantined','delete_pending','deleted')",
            name="ck_assets_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("notebook_upload_batches.id", ondelete="SET NULL"), nullable=True,
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ready", server_default="ready")
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AssetMigrationIssue(Base):
    """Persistent audit rows for legacy files intentionally left unmapped."""

    __tablename__ = "asset_migration_issues"
    __table_args__ = (
        UniqueConstraint(
            "source_table", "source_id", "issue_code",
            name="uq_asset_migration_issue_source_code",
        ),
        Index("ix_asset_migration_issues_unresolved", "resolved_at", "source_table"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_table: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(60), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotebookAsset(Base):
    """Notebook ownership/use link. Exactly one active row owns each asset."""

    __tablename__ = "notebook_assets"
    __table_args__ = (
        Index(
            "uq_notebook_assets_one_active_owner_per_asset", "asset_id", unique=True,
            sqlite_where=text("is_owner = 1 AND detached_at IS NULL"),
        ),
        Index(
            "uq_notebook_assets_active_use", "notebook_id", "asset_id", "role", unique=True,
            sqlite_where=text("detached_at IS NULL"),
        ),
        Index("ix_notebook_assets_notebook", "notebook_id", "created_at"),
        UniqueConstraint("id", "notebook_id", "asset_id", name="uq_notebook_asset_owner_ref"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_owner: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    detached_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotebookCoverAsset(Base):
    """Compatibility pointer for legacy cover API fields."""

    __tablename__ = "notebook_cover_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="CASCADE",
        ),
    )

    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True, nullable=False)
    owner_link_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NotebookRevisionAsset(Base):
    """Pins assets referenced by an immutable Notebook history snapshot."""

    __tablename__ = "notebook_revision_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "notebook_id"],
            ["notebook_document_revisions.id", "notebook_document_revisions.notebook_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "asset_id", name="uq_notebook_revision_asset"),
        Index("ix_notebook_revision_assets_asset", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    notebook_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_link_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AssetProcessingJob(Base):
    """Image/OCR job independent of Material's document parser projection."""

    __tablename__ = "asset_processing_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="CASCADE",
        ),
        Index("ix_asset_processing_jobs_asset", "asset_id", "created_at"),
        Index(
            "uq_asset_processing_jobs_active", "asset_id", unique=True,
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    owner_link_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="image_parse")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AssetParseResult(Base):
    __tablename__ = "asset_parse_results"
    __table_args__ = (Index("ix_asset_parse_results_asset", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("asset_processing_jobs.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotebookGenerationJob(Base):
    __tablename__ = "notebook_generation_jobs"
    __table_args__ = (
        UniqueConstraint("notebook_id", "idempotency_key", name="uq_notebook_generation_idempotency"),
        UniqueConstraint("id", "notebook_id", name="uq_notebook_generation_job_id_notebook"),
        Index("ix_notebook_generation_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    base_document_revision: Mapped[int] = mapped_column(nullable=False)
    input_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[int] = mapped_column(default=2, nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Document IR input identity and generation provenance.
    parse_run_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    ir_fingerprints_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", nullable=False)
    generator: Mapped[str] = mapped_column(String(40), default="deepseek", server_default="deepseek", nullable=False)
    generator_version: Mapped[str] = mapped_column(String(40), default="1", server_default="1", nullable=False)
    knowledge_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_map_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotebookGenerationCandidate(Base):
    """Legacy review-candidate table.

    The worker never produced candidates (the document was appended directly).
    The table is kept read-only for historical rows; the API is retired.
    """

    __tablename__ = "notebook_generation_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "notebook_id"],
            ["notebook_generation_jobs.id", "notebook_generation_jobs.notebook_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", name="uq_notebook_candidate_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)


class DocumentParseRun(Base):
    """One immutable parse attempt for one Asset (versioned document evidence)."""

    __tablename__ = "document_parse_runs"
    __table_args__ = (
        Index("uq_document_parse_runs_current", "asset_id", unique=True,
              sqlite_where=text("is_current = 1")),
        Index("ix_document_parse_runs_asset", "asset_id", "created_at"),
        Index("ix_document_parse_runs_status", "status", "created_at"),
        CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_document_parse_run_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", nullable=False)
    ir_version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), default="unknown", server_default="unknown", nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), default="0", server_default="0", nullable=False)
    config_version: Mapped[str] = mapped_column(String(80), default="v1", server_default="v1", nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", nullable=False)
    is_current: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    text_chars: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quality_status: Mapped[str] = mapped_column(String(20), default="failed", server_default="failed", nullable=False)
    quality_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", nullable=False)
    markdown_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "page_number", name="uq_document_pages_run_number"),
        Index("ix_document_pages_run", "parse_run_id", "page_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("document_parse_runs.id", ondelete="CASCADE"), nullable=False,
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    width: Mapped[float | None] = mapped_column(nullable=True)
    height: Mapped[float | None] = mapped_column(nullable=True)
    rotation: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    render_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extraction: Mapped[str] = mapped_column(String(20), default="native_text", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="parsed", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "block_id", name="uq_document_blocks_run_block"),
        Index("ix_document_blocks_run_order", "parse_run_id", "global_order"),
        Index("ix_document_blocks_page_order", "page_id", "order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("document_parse_runs.id", ondelete="CASCADE"), nullable=False,
    )
    page_id: Mapped[str] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=False,
    )
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    global_order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    level: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    figure_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction: Mapped[str] = mapped_column(String(20), default="native_text", nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "section_id", name="uq_document_sections_run_section"),
        Index("ix_document_sections_run_order", "parse_run_id", "order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("document_parse_runs.id", ondelete="CASCADE"), nullable=False,
    )
    section_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    level: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    page_start: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    page_end: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    block_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class DocumentChunk(Base):
    """Rebuildable retrieval chunk derived from a parse run."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_run_order", "parse_run_id", "order"),
        Index("ix_document_chunks_asset", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("document_parse_runs.id", ondelete="CASCADE"), nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_numbers_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    block_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NotebookBlockSource(Base):
    """Traceability: a Notebook body block came from these document blocks."""

    __tablename__ = "notebook_block_sources"
    __table_args__ = (
        UniqueConstraint("notebook_id", "block_id", "document_block_id",
                         name="uq_notebook_block_source_edge"),
        Index("ix_notebook_block_sources_block", "notebook_id", "block_id"),
        Index("ix_notebook_block_sources_run", "parse_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parse_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_block_id: Mapped[str] = mapped_column(String(36), nullable=False)
    page_number: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    body_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NotebookSection(Base):
    """Derived index of Notebook body headings/sections (rebuildable)."""

    __tablename__ = "notebook_sections"
    __table_args__ = (
        UniqueConstraint("notebook_id", "block_id", name="uq_notebook_sections_block"),
        Index("ix_notebook_sections_order", "notebook_id", "order"),
        Index("ix_notebook_sections_course", "course_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True,
    )
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    level: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    heading: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    revision: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NotebookEditSuggestion(Base):
    """Pending Agent edit proposal against one Notebook document revision."""

    __tablename__ = "notebook_edit_suggestions"
    __table_args__ = (
        Index("ix_notebook_edit_suggestions_status", "notebook_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    base_revision: Mapped[int] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ops_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    proposed_document_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)


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
    notebook_id: Mapped[str | None] = mapped_column(ForeignKey("notebooks.id"), nullable=True, index=True)
    tree_slot: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
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
    # Legacy body retirement: content is copied into Notebook.document_json and
    # the row becomes read-only evidence.  Columns are kept so the migration is
    # auditable and reversible without deleting user content.
    migrated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    migrated_revision: Mapped[int | None] = mapped_column(nullable=True)
    migration_batch: Mapped[str | None] = mapped_column(String(36), nullable=True)

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
    # 会话归属：course（整门课程）/ global（跨课程）/ note（锁定某篇笔记）。
    # 首次提问时确定，之后同一会话内改范围不搬家，避免历史列表跳动。
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 仅 scope='note' 时写入，存笔记 id 与标题快照（笔记改名不回溯历史）。
    note_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
    # Document IR / Notebook evidence (source_ref_id remains for legacy rows).
    notebook_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_block_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    page_numbers_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    parse_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    body_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notebook_revision: Mapped[int | None] = mapped_column(nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
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


def default_notebook_id(connection, course_id: str) -> str:
    """Compatibility helper for explicit course UI actions only."""
    connection.execute(Course.__table__.update().where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision))
    book_id = connection.scalar(select(Notebook.id).where(
        Notebook.course_id == course_id, Notebook.is_default.is_(True)))
    if book_id is None:
        course = connection.execute(select(Course.name, Course.notebook_order_revision).where(
            Course.id == course_id)).one()
        slot = connection.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course_id))
        book_id = new_id()
        connection.execute(Notebook.__table__.insert().values(
            id=book_id, course_id=course_id, title=f"{course.name}·课程笔记",
            is_default=True, tree_slot=0 if slot is None else slot + 1,
            display_order=0 if slot is None else slot + 1,
            order_revision=course.notebook_order_revision))
    return book_id


@event.listens_for(Note, "before_insert")
def assign_notebook(mapper, connection, target) -> None:
    """Derive legacy Note placement from its source Material / Notebook.

    ``Material.course_id`` is a deprecated field and no longer decides course
    ownership; a Notebook-owned Material inherits the Notebook.
    """
    if target.material_id:
        material = connection.execute(select(Material.notebook_id).where(
            Material.id == target.material_id)).one()
        if target.notebook_id is not None and target.notebook_id != material.notebook_id:
            raise ValueError("Note and material must belong to the same notebook")
        if material.notebook_id is not None:
            target.notebook_id = material.notebook_id
    # Legacy course knowledge Notes can remain unbound. Never select a course
    # default Notebook on their behalf; Notebook-backed Notes pass an explicit
    # ID (or inherit it from a Notebook-owned Material above).
    if target.notebook_id is None:
        return
    owner = connection.scalar(select(Notebook.course_id).where(Notebook.id == target.notebook_id))
    if owner is not None and owner != target.course_id:
        raise ValueError("Notebook must belong to the same course")
    next_slot = connection.scalar(Notebook.__table__.update().where(Notebook.id == target.notebook_id)
                                  .values(next_note_slot=Notebook.next_note_slot + 1)
                                  .returning(Notebook.next_note_slot))
    target.tree_slot = next_slot - 1
