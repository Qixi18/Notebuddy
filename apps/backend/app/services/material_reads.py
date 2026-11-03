"""Application queries for legacy Material views and course file summaries."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    Material,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    ProcessingJob,
    WebSource,
)
from app.services.course_scope import material_course_id, materials_for_course
from app.services.deletion import impact_preview
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_course, require_material, require_notebook


def list_course_materials(db: Session, course_id: str) -> list[Material]:
    require_course(db, course_id)
    return sorted(materials_for_course(db, course_id), key=lambda item: item.created_at,
                  reverse=True)


def list_course_notebook_files(db: Session, course_id: str) -> dict:
    require_course(db, course_id)
    notebooks = db.scalars(select(Notebook).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
    )).all()
    titles = {book.id: book.title for book in notebooks}
    files: list[dict] = []
    for item in sorted(materials_for_course(db, course_id), key=lambda row: row.created_at,
                       reverse=True):
        files.append({
            "id": item.id, "notebook_id": item.notebook_id,
            "notebook_title": titles.get(item.notebook_id) if item.notebook_id else None,
            "original_filename": item.original_filename,
            "media_type": item.media_type or "application/octet-stream",
            "size_bytes": item.size_bytes, "created_at": item.created_at,
            "status": item.status,
        })
    notebook_assets = db.execute(select(
        Asset, NotebookAsset.notebook_id, NotebookAsset.role,
    ).join(NotebookAsset, NotebookAsset.asset_id == Asset.id).where(
        NotebookAsset.notebook_id.in_(titles), NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None), Asset.media_type == "image",
        Asset.state.in_(("ready", "missing", "quarantined")),
        NotebookAsset.role.in_(("source_material", "inline_image", "cover")),
    )).all() if titles else []
    for asset, owner_notebook_id, _role in notebook_assets:
        files.append({
            "id": asset.id, "notebook_id": owner_notebook_id,
            "notebook_title": titles[owner_notebook_id],
            "original_filename": asset.original_name, "media_type": asset.mime_type,
            "size_bytes": asset.byte_size, "created_at": asset.created_at,
            "status": asset.state,
        })
    legacy_attachments = db.scalars(select(NotebookAttachment).where(
        NotebookAttachment.notebook_id.in_(titles), NotebookAttachment.asset_id.is_(None),
    )).all() if titles else []
    for attachment in legacy_attachments:
        files.append({
            "id": attachment.id, "notebook_id": attachment.notebook_id,
            "notebook_title": titles[attachment.notebook_id],
            "original_filename": attachment.original_filename,
            "media_type": attachment.mime, "size_bytes": attachment.size_bytes,
            "created_at": attachment.created_at, "status": "legacy_unmapped",
        })
    files.sort(key=lambda item: item["created_at"], reverse=True)
    return {"course_id": course_id, "file_count": len(files),
            "total_size_bytes": sum(item["size_bytes"] for item in files),
            "files": files}


def list_deleted_materials(db: Session, course_id: str) -> list[Material]:
    require_course(db, course_id)
    rows = materials_for_course(db, course_id, include_deleted=True)
    return sorted((item for item in rows if item.deleted_at is not None),
                  key=lambda item: item.deleted_at, reverse=True)


def preview_material_deletion(db: Session, material_id: str) -> dict:
    material = require_material(db, material_id)
    return impact_preview(db, course_id=material_course_id(db, material),
                          material_id=material.id)


def list_notebook_materials(db: Session, notebook_id: str) -> list[Material]:
    require_notebook(db, notebook_id)
    return list(db.scalars(select(Material).where(
        Material.notebook_id == notebook_id, Material.deleted_at.is_(None),
    ).order_by(Material.created_at.desc())).all())


def get_latest_material_job(db: Session, material_id: str) -> ProcessingJob:
    require_material(db, material_id)
    job = db.scalar(select(ProcessingJob).where(
        ProcessingJob.material_id == material_id,
    ).order_by(ProcessingJob.created_at.desc()).limit(1))
    if job is None:
        raise ApplicationError(404, "资料没有处理任务")
    return job


def list_course_web_sources(db: Session, course_id: str) -> list[WebSource]:
    require_course(db, course_id)
    return list(db.scalars(select(WebSource).where(
        WebSource.course_id == course_id,
    ).order_by(WebSource.retrieved_at.desc())).all())


def list_material_web_sources(db: Session, material_id: str) -> list[WebSource]:
    require_material(db, material_id)
    return list(db.scalars(select(WebSource).where(
        WebSource.material_id == material_id,
    ).order_by(WebSource.retrieved_at.desc())).all())
