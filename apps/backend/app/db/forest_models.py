"""Curriculum, forest jobs, and cross-course relation tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.model_utils import new_id, utc_now


class ForestCourseProfile(Base):
    __tablename__ = "forest_course_profiles"

    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    semester: Mapped[int | None] = mapped_column(nullable=True)
    level: Mapped[str] = mapped_column(String(30), default="unspecified", server_default="unspecified", nullable=False)
    learning_state: Mapped[str] = mapped_column(String(30), default="planned", server_default="planned", nullable=False)
    position: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    revision: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)


class CurriculumImport(Base):
    __tablename__ = "curriculum_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_text: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", nullable=False)
    mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    rows_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ForestJob(Base):
    __tablename__ = "forest_jobs"
    __table_args__ = (
        Index("ix_forest_jobs_status", "status", "created_at"),
        Index("uq_forest_jobs_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    curriculum_import_id: Mapped[str | None] = mapped_column(ForeignKey("curriculum_imports.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_snapshot_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    completed_source_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)


class CrossCourseRelation(Base):
    __tablename__ = "cross_course_relations"
    __table_args__ = (
        UniqueConstraint("source_note_id", "target_note_id", "relation_type", name="uq_cross_course_relations_endpoints_type"),
        Index("ix_cross_course_relations_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    target_course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    source_note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    target_note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    source_revision: Mapped[int] = mapped_column(nullable=False)
    target_revision: Mapped[int] = mapped_column(nullable=False)
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", nullable=False)
    origin: Mapped[str] = mapped_column(String(30), default="ai", server_default="ai", nullable=False)
    activation_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    target_ref_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
