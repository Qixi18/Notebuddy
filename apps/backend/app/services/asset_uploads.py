"""Application use cases for uploading course and Notebook source assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Asset, AssetProcessingJob, Course, Material, Notebook, ProcessingJob
from app.services.errors import ApplicationError
from app.services.image_assets import ImageUploadRejected, ingest_source_image
from app.services.notebook_generation_inputs import ensure_upload_batch, register_generation_input
from app.services.uploads import UploadRejected, ingest_document


@dataclass(frozen=True)
class MaterialUploadResult:
    material: Material
    job: ProcessingJob
    upload_batch_id: str | None


@dataclass(frozen=True)
class AssetUploadResult:
    asset: Asset
    job: AssetProcessingJob | None
    upload_batch_id: str


def _active_notebook(db: Session, notebook_id: str) -> Notebook:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    return notebook


def _active_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise ApplicationError(404, "课程不存在")
    return course


def _upload_document(
    db: Session,
    *,
    notebook: Notebook,
    source: BinaryIO,
    filename: str,
    lecture_title: str,
    topic_title: str,
    media_type: str | None,
    batch_id: str,
    processing_route: str | None,
    allow_duplicate: bool = False,
    idempotency_key: str | None = None,
) -> tuple[Material, ProcessingJob]:
    try:
        material, job = ingest_document(
            db,
            course_id=notebook.course_id,
            notebook_id=notebook.id,
            source=source,
            filename=filename,
            lecture_title=lecture_title,
            topic_title=topic_title,
            media_type=media_type,
            allow_duplicate=allow_duplicate,
            idempotency_key=idempotency_key,
            upload_batch_id=batch_id,
            processing_route=processing_route,
        )
    except UploadRejected as exc:
        db.rollback()
        raise ApplicationError(exc.status_code, str(exc)) from exc
    if material.asset_id is None:
        raise ApplicationError(500, "上传资料未创建资源记录")
    try:
        register_generation_input(
            db, notebook_id=notebook.id, asset_id=material.asset_id,
            batch_id=batch_id, parse_kind="material", parse_job_id=job.id,
        )
        db.commit()
    except Exception:
        # The durable upload/job is recoverable from its UploadBatch; don't
        # leave a failed GenerationInput transaction attached to this Session.
        db.rollback()
        raise
    return material, job


def upload_course_material(
    db: Session,
    *,
    course_id: str,
    source: BinaryIO,
    filename: str,
    lecture_title: str,
    topic_title: str,
    media_type: str | None,
    notebook_id: str | None,
    allow_duplicate: bool,
    idempotency_key: str | None,
    upload_batch_id: str | None,
    processing_route: str | None,
) -> MaterialUploadResult:
    course = _active_course(db, course_id)
    notebook = _active_notebook(db, notebook_id) if notebook_id else None
    if notebook is not None:
        if notebook.course_id != course.id:
            raise ApplicationError(409, "所选笔记不属于该课程")
        batch = ensure_upload_batch(
            db, notebook.id, upload_batch_id,
            close_if_new=upload_batch_id is None,
            processing_route=processing_route,
        )
        batch_id = batch.id
        route = batch.processing_route
    else:
        batch_id = None
        route = processing_route
    try:
        # ingest_document validates and snapshots this route. Batch policy is
        # applied above so every file in one batch uses the same route.
        if notebook is None:
            material, job = ingest_document(
                db, course_id=course.id, source=source, filename=filename,
                lecture_title=lecture_title, topic_title=topic_title,
                media_type=media_type, allow_duplicate=allow_duplicate,
                idempotency_key=idempotency_key, notebook_id=None,
                upload_batch_id=None, processing_route=route,
            )
        else:
            material, job = _upload_document(
                db, notebook=notebook, source=source, filename=filename,
                lecture_title=lecture_title, topic_title=topic_title,
                media_type=media_type, batch_id=batch_id,
                processing_route=route,
                allow_duplicate=allow_duplicate, idempotency_key=idempotency_key,
            )
    except UploadRejected as exc:
        db.rollback()
        raise ApplicationError(exc.status_code, str(exc)) from exc
    return MaterialUploadResult(material, job, batch_id)


def upload_notebook_file(
    db: Session,
    *,
    notebook_id: str,
    source: BinaryIO,
    filename: str,
    lecture_title: str,
    topic_title: str,
    media_type: str | None,
    allow_duplicate: bool,
    idempotency_key: str | None,
    upload_batch_id: str | None,
    processing_route: str | None,
) -> MaterialUploadResult:
    notebook = _active_notebook(db, notebook_id)
    batch = ensure_upload_batch(
        db, notebook.id, upload_batch_id,
        close_if_new=upload_batch_id is None,
        processing_route=processing_route,
    )
    material, job = _upload_document(
        db, notebook=notebook, source=source, filename=filename,
        lecture_title=lecture_title, topic_title=topic_title,
        media_type=media_type, batch_id=batch.id,
        processing_route=batch.processing_route,
        allow_duplicate=allow_duplicate, idempotency_key=idempotency_key,
    )
    return MaterialUploadResult(material, job, batch.id)


def upload_notebook_asset(
    db: Session,
    *,
    notebook_id: str,
    filename: str,
    source: BinaryIO,
    image_data: bytes | None,
    media_type: str | None,
    upload_batch_id: str | None,
    processing_route: str | None,
) -> AssetUploadResult:
    notebook = _active_notebook(db, notebook_id)
    batch = ensure_upload_batch(
        db, notebook.id, upload_batch_id,
        close_if_new=upload_batch_id is None,
        processing_route=processing_route,
    )
    extension = Path(filename).suffix.lower()
    if extension in settings.allowed_extensions:
        material, job = _upload_document(
            db, notebook=notebook, source=source, filename=filename,
            lecture_title=filename, topic_title="", media_type=media_type,
            batch_id=batch.id, processing_route=batch.processing_route,
        )
        asset = db.get(Asset, material.asset_id)
        if asset is None:
            raise ApplicationError(500, "资源元数据未创建")
        return AssetUploadResult(asset, None, batch.id)

    data = image_data
    if data is None:
        data = source.read(20 * 1024 * 1024 + 1)
    try:
        asset, job = ingest_source_image(
            db, notebook_id=notebook.id, filename=filename, data=data,
            upload_batch_id=batch.id, processing_route=batch.processing_route,
        )
    except ImageUploadRejected as exc:
        db.rollback()
        raise ApplicationError(exc.status_code, str(exc)) from exc
    try:
        register_generation_input(
            db, notebook_id=notebook.id, asset_id=asset.id, batch_id=batch.id,
            parse_kind="image", parse_job_id=job.id if job else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AssetUploadResult(asset, job, batch.id)
