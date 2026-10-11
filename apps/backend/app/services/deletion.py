"""Reversible local deletion with an impact preview and pre-change checkpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.checkpoint import create_checkpoint
from app.db.models import (
    Course,
    KnowledgeNode,
    Material,
    MaterialPage,
    Note,
    PageBlock,
    ProcessingJob,
    SourceRef,
)
from app.notes.notebook import bump_order_revision


class DeletionConflict(ValueError):
    pass


def _material_ids(db: Session, course_id: str) -> list[str]:
    return list(db.scalars(select(Material.id).where(
        Material.course_id == course_id, Material.deleted_at.is_(None)
    )).all())


def impact_preview(db: Session, *, course_id: str, material_id: str | None = None) -> dict:
    material_ids = [material_id] if material_id else _material_ids(db, course_id)
    materials = list(db.scalars(select(Material).where(Material.id.in_(material_ids))).all()) if material_ids else []
    pages = db.scalar(select(func.count(MaterialPage.id)).where(
        MaterialPage.material_id.in_(material_ids), MaterialPage.is_active.is_(True)
    )) if material_ids else 0
    refs = db.scalar(select(func.count(SourceRef.id)).join(PageBlock).join(MaterialPage).where(
        MaterialPage.material_id.in_(material_ids),
        MaterialPage.is_active.is_(True),
        SourceRef.status == "active",
    )) if material_ids else 0
    node_ids = list(db.scalars(select(KnowledgeNode.id).distinct()
        .join(KnowledgeNode.source_refs).join(SourceRef.page_block).join(PageBlock.page)
        .where(
            MaterialPage.material_id.in_(material_ids),
            MaterialPage.is_active.is_(True),
            SourceRef.status == "active",
        )).all()) if material_ids else []
    locked = db.scalar(select(func.count(Note.id)).where(
        Note.knowledge_node_id.in_(node_ids), Note.user_locked.is_(True)
    )) if node_ids else 0
    active = db.scalar(select(func.count(ProcessingJob.id)).where(
        ProcessingJob.material_id.in_(material_ids),
        ProcessingJob.status.in_(["pending", "processing"])
    )) if material_ids else 0
    return {
        "course_id": course_id, "material_id": material_id,
        "materials": len(materials), "pages": pages or 0, "source_refs": refs or 0,
        "knowledge_nodes_touched": len(node_ids), "user_notes_protected": locked or 0,
        "original_bytes": sum(item.size_bytes for item in materials),
        "active_jobs": active or 0,
        "action": "soft_delete_with_checkpoint",
    }


def _checkpoint() -> None:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    create_checkpoint(settings.data_dir, settings.backups_dir / f"pre-delete-{suffix}")


def soft_delete_material(db: Session, material: Material) -> dict:
    preview = impact_preview(db, course_id=material.course_id, material_id=material.id)
    if preview["active_jobs"]:
        raise DeletionConflict("资料仍有处理任务；完成或取消后再删除")
    _checkpoint()
    material.deleted_at = datetime.now(UTC)
    bump_order_revision(db, material.course_id)
    db.commit()
    return preview


def soft_delete_course(db: Session, course: Course) -> dict:
    preview = impact_preview(db, course_id=course.id)
    if preview["active_jobs"]:
        raise DeletionConflict("课程仍有处理任务；完成或取消后再删除")
    _checkpoint()
    course.deleted_at = datetime.now(UTC)
    db.commit()
    return preview
