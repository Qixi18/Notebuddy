"""Notebook resource application use cases."""
from __future__ import annotations

import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookCoverAsset,
    utc_now,
)
from app.notes.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentRejected,
    sniff_image_mime,
    store_attachment,
)
from app.services.image_assets import finalize_staged_image, write_staged_image


def create_notebook_attachment(
    db: Session, notebook_id: str, *, filename: str, data: bytes,
) -> NotebookAttachment:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    try:
        attachment = store_attachment(
            db, notebook_id=notebook_id, filename=filename, data=data,
        )
        db.commit()
        db.refresh(attachment)
        return attachment
    except AttachmentRejected as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def delete_notebook_cover(db: Session, notebook_id: str) -> None:
    book = db.get(Notebook, notebook_id)
    if book is None:
        raise HTTPException(404, "笔记不存在")
    cover = db.get(NotebookCoverAsset, notebook_id)
    asset = db.get(Asset, cover.asset_id) if cover else None
    if cover:
        link = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == cover.asset_id,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        ))
        if link:
            link.detached_at = utc_now()
        db.delete(cover)
    if asset:
        asset.state = "delete_pending"
    book.cover_filename = book.cover_mime = None
    db.commit()


def replace_notebook_cover(db: Session, notebook_id: str, *, filename: str, data: bytes) -> Notebook:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    mime = sniff_image_mime(data)
    if not data or len(data) > MAX_ATTACHMENT_BYTES or mime is None:
        raise HTTPException(413 if len(data) > MAX_ATTACHMENT_BYTES else 422,
                            "封面需为不超过 10 MB 的 PNG、JPEG、WebP 或 GIF 图片")
    extension = {"image/png": ".png", "image/jpeg": ".jpg",
                 "image/webp": ".webp", "image/gif": ".gif"}[mime]
    asset_id = str(uuid.uuid4())
    storage_name = f"{notebook_id}-{asset_id}{extension}"
    staging_path = write_staged_image(asset_id, data)
    old_cover = db.get(NotebookCoverAsset, notebook_id)
    asset = Asset(
        id=asset_id, source_type="user_upload", media_type="image", mime_type=mime,
        extension=extension, original_name=(filename or "cover")[:255],
        storage_key=f"notebook-covers/{notebook_id}/{asset_id}{extension}", byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), state="staging",
        created_at=utc_now(), verified_at=None,
    )
    db.add(asset)
    db.flush()
    owner_link = NotebookAsset(notebook_id=notebook_id, asset_id=asset_id, role="cover",
                               is_owner=True, created_at=utc_now())
    db.add(owner_link)
    db.flush()
    if old_cover:
        old_link = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == old_cover.asset_id,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        ))
        if old_link:
            old_link.detached_at = utc_now()
        db.delete(old_cover)
    db.add(NotebookCoverAsset(notebook_id=notebook_id, asset_id=asset_id,
                              owner_link_id=owner_link.id, created_at=utc_now()))
    book.cover_filename, book.cover_mime = storage_name, mime
    try:
        db.commit()
    except Exception:
        db.rollback()
        staging_path.unlink(missing_ok=True)
        raise
    finalize_staged_image(db, asset)
    return book


def mark_asset_missing(db: Session, asset_id: str) -> None:
    asset = db.get(Asset, asset_id)
    if asset is not None and asset.state == "ready":
        asset.state = "missing"
        db.commit()
