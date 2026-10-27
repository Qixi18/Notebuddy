"""Persist Notebook source images and queue optional OCR without Material rows."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import Asset, AssetProcessingJob, Notebook, NotebookAsset, utc_now
from app.notes.attachments import image_dimensions, sniff_image_mime

MAX_SOURCE_IMAGE_BYTES = 20 * 1024 * 1024
logger = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg"}


class ImageUploadRejected(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _safe_path(key: str) -> Path:
    root = settings.data_dir.resolve()
    candidate = root / key
    try:
        path = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise ImageUploadRejected("资源路径不可访问", 400) from exc
    if not path.is_relative_to(root) or path == root:
        raise ImageUploadRejected("资源路径不合法", 400)
    current = candidate
    while current != root:
        if current.is_symlink():
            raise ImageUploadRejected("资源路径包含符号链接", 400)
        current = current.parent
    return path


def write_staged_image(asset_id: str, data: bytes) -> Path:
    staging = _safe_path(f"staging/{asset_id}.upload")
    staging.parent.mkdir(parents=True, exist_ok=True)
    with staging.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(staging.parent)
    return staging


def finalize_staged_image(db: Session, asset: Asset) -> AssetProcessingJob | None:
    """Idempotently move a committed staging upload to its immutable key."""
    if asset.state != "staging":
        return db.scalar(select(AssetProcessingJob).where(
            AssetProcessingJob.asset_id == asset.id,
        ).order_by(AssetProcessingJob.created_at.desc()))
    final = _safe_path(asset.storage_key)
    staging = _safe_path(f"staging/{asset.id}.upload")
    final.parent.mkdir(parents=True, exist_ok=True)
    final_digest = _file_digest(final) if final.is_file() else None
    staging_digest = _file_digest(staging) if staging.is_file() else None
    if final_digest == asset.sha256:
        digest = final_digest
        staging.unlink(missing_ok=True)
    elif staging_digest == asset.sha256:
        try:
            os.replace(staging, final)
            _fsync_directory(final.parent)
        except OSError:
            logger.exception("Could not finalize staged image Asset %s", asset.id)
            return None
        digest = staging_digest
    elif final_digest is not None:
        digest = final_digest
    elif staging_digest is not None:
        try:
            os.replace(staging, final)
            _fsync_directory(final.parent)
        except OSError:
            logger.exception("Could not finalize staged image Asset %s", asset.id)
            return None
        digest = staging_digest
    else:
        asset.state = "missing"
        db.commit()
        return None
    if digest != asset.sha256:
        asset.state = "quarantined"
        db.commit()
        return None
    asset.state = "ready"
    asset.verified_at = utc_now()
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset.id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    job = None
    if owner is not None and owner.role == "source_material":
        job = db.scalar(select(AssetProcessingJob).where(
            AssetProcessingJob.asset_id == asset.id,
            AssetProcessingJob.status.in_(("pending", "processing")),
        ))
    if owner is not None and owner.role == "source_material" and job is None:
        job = AssetProcessingJob(
            asset_id=asset.id, notebook_id=owner.notebook_id, owner_link_id=owner.id,
            kind="image_parse", status="pending", attempt_count=0,
        )
        db.add(job)
    db.commit()
    db.refresh(asset)
    return job


def ingest_source_image(
    db: Session, *, notebook_id: str, filename: str, data: bytes,
    upload_batch_id: str | None = None,
) -> tuple[Asset, AssetProcessingJob | None]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise ImageUploadRejected("笔记不存在", 404)
    if not data:
        raise ImageUploadRejected("图片内容为空")
    if len(data) > MAX_SOURCE_IMAGE_BYTES:
        raise ImageUploadRejected("原始图片不能超过 20 MB", 413)
    mime = sniff_image_mime(data)
    if mime not in IMAGE_EXTENSIONS:
        raise ImageUploadRejected("原始学习资料仅支持 PNG 或 JPG/JPEG")
    try:
        image_dimensions(data, mime)
    except ValueError as exc:
        raise ImageUploadRejected(str(exc)) from exc
    asset_id = new_id()
    extension = IMAGE_EXTENSIONS[mime]
    storage_key = f"assets/{asset_id[:2]}/{asset_id}{extension}"
    staging = write_staged_image(asset_id, data)
    now = utc_now()
    asset = Asset(
        id=asset_id, source_type="user_upload", media_type="image", mime_type=mime,
        extension=extension, original_name=Path(filename or "image").name[:255],
        storage_key=storage_key, byte_size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        state="staging", created_at=now, upload_batch_id=upload_batch_id,
    )
    db.add_all([asset, NotebookAsset(
        notebook_id=notebook_id, asset_id=asset_id, role="source_material",
        is_owner=True, created_at=now,
    )])
    try:
        db.commit()
    except Exception:
        db.rollback()
        staging.unlink(missing_ok=True)
        raise
    db.refresh(asset)
    job = finalize_staged_image(db, asset)
    return asset, job


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability; Windows does not open directories this way."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def reconcile_staged_images(db: Session, *, limit: int = 50) -> int:
    assets = db.scalars(select(Asset).where(
        Asset.state == "staging", Asset.media_type == "image",
    )
                        .order_by(Asset.created_at).limit(limit)).all()
    for asset in assets:
        finalize_staged_image(db, asset)
    return len(assets)
