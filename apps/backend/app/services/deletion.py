"""Reversible local deletion with an impact preview and pre-change checkpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.checkpoint import create_checkpoint
from app.db.models import (
    AssetProcessingJob,
    Course,
    DocumentBlock,
    DocumentPage,
    DocumentParseRun,
    ForestJob,
    Material,
    Notebook,
    NotebookBlockSource,
    NotebookGenerationJob,
    NotebookSection,
    ProcessingJob,
)
from app.notes.notebook import bump_order_revision
from app.services.course_scope import material_course_id


class DeletionConflict(ValueError):
    pass


def _material_ids(db: Session, course_id: str) -> list[str]:
    return list(db.scalars(
        select(Material.id)
        .join(Notebook, Notebook.id == Material.notebook_id)
        .where(Notebook.course_id == course_id, Material.deleted_at.is_(None))
    ).all())


def impact_preview(db: Session, *, course_id: str | None, material_id: str | None = None) -> dict:
    material_ids = [material_id] if material_id else (_material_ids(db, course_id) if course_id else [])
    materials = list(db.scalars(select(Material).where(Material.id.in_(material_ids))).all()) if material_ids else []
    asset_ids = [item.asset_id or item.id for item in materials]
    run_ids = list(db.scalars(select(DocumentParseRun.id).where(
        DocumentParseRun.asset_id.in_(asset_ids),
        DocumentParseRun.is_current.is_(True),
    )).all()) if asset_ids else []
    pages = db.scalar(select(func.count(DocumentPage.id)).where(
        DocumentPage.parse_run_id.in_(run_ids),
    )) if run_ids else 0
    blocks = db.scalar(select(func.count(DocumentBlock.id)).where(
        DocumentBlock.parse_run_id.in_(run_ids),
    )) if run_ids else 0
    citations = db.scalar(select(func.count(NotebookBlockSource.id)).where(
        NotebookBlockSource.parse_run_id.in_(run_ids),
    )) if run_ids else 0
    active = db.scalar(select(func.count(ProcessingJob.id)).where(
        ProcessingJob.material_id.in_(material_ids),
        ProcessingJob.status.in_(["pending", "processing"])
    )) if material_ids else 0
    image_active = db.scalar(select(func.count(AssetProcessingJob.id)).where(
        AssetProcessingJob.asset_id.in_(asset_ids),
        AssetProcessingJob.status.in_(["pending", "processing"]),
    )) if asset_ids else 0
    generation_active = db.scalar(select(func.count(NotebookGenerationJob.id)).where(
        NotebookGenerationJob.notebook_id.in_([item.notebook_id for item in materials if item.notebook_id]),
        NotebookGenerationJob.status.in_(["pending", "processing"]),
    )) if materials else 0
    # A running relation job may be reading evidence from any target course.
    # Pending jobs only pin their source course; completed/failed jobs never pin it.
    forest_active = db.scalar(select(func.count(ForestJob.id)).where(
        ForestJob.kind.in_(["cross_course_relations", "validate_legacy_relations"]),
        or_(
            and_(ForestJob.course_id == course_id,
                 ForestJob.status.in_(["pending", "processing"])),
            ForestJob.status == "processing",
        ),
    )) or 0
    return {
        "course_id": course_id, "material_id": material_id,
        "materials": len(materials), "pages": pages or 0,
        "source_refs": citations or 0,
        "document_blocks": blocks or 0,
        "knowledge_nodes_touched": 0,
        "user_notes_protected": 0,
        "original_bytes": sum(item.size_bytes for item in materials),
        "active_jobs": (active or 0) + (image_active or 0) + (generation_active or 0) + forest_active,
        "action": "soft_delete_with_checkpoint",
    }


def _checkpoint() -> None:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    create_checkpoint(settings.data_dir, settings.backups_dir / f"pre-delete-{suffix}")


def soft_delete_material(db: Session, material: Material) -> dict:
    course_id = material_course_id(db, material)
    preview = impact_preview(db, course_id=course_id, material_id=material.id)
    if preview["active_jobs"]:
        raise DeletionConflict("资料仍有处理任务；完成或取消后再删除")
    _checkpoint()
    material.deleted_at = datetime.now(UTC)
    bump_order_revision(db, course_id, material.notebook_id)
    db.commit()
    return preview


def soft_delete_course(db: Session, course: Course) -> dict:
    preview = impact_preview(db, course_id=course.id)
    if preview["active_jobs"]:
        raise DeletionConflict("课程仍有处理任务；完成或取消后再删除")
    _checkpoint()
    db.execute(update(Notebook).where(Notebook.course_id == course.id).values(
        course_id=None, tree_slot=0, display_order=0, order_revision=0, is_default=False))
    db.execute(update(NotebookSection).where(NotebookSection.course_id == course.id).values(
        course_id=None))
    course.deleted_at = datetime.now(UTC)
    db.commit()
    return preview
