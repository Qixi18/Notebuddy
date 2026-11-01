"""Notebook 路由 · resources。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    Asset,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookCoverAsset,
    NotebookRevisionAsset,
    utc_now,
)
from app.notes.assets import AssetUnavailable, has_live_asset_references, storage_path
from app.notes.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentRejected,
    attachment_path,
    public_url,
    store_attachment,
)
from app.schemas.notebook import NotebookAttachmentRead

from .common import (
    _cover_url,
    ensure_notebook,
)

router = APIRouter()

@router.put("/notebooks/{notebook_id}/cover")
async def upload_notebook_cover(notebook_id: str, file: UploadFile = File(...),
                                db: Session = Depends(get_db)):
    import hashlib
    import uuid

    from app.notes.attachments import MAX_ATTACHMENT_BYTES, sniff_image_mime
    from app.services.image_assets import finalize_staged_image, write_staged_image

    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    mime = sniff_image_mime(data)
    if not data or len(data) > MAX_ATTACHMENT_BYTES or mime is None:
        raise HTTPException(413 if len(data) > MAX_ATTACHMENT_BYTES else 422,
                            "封面需为不超过 10 MB 的 PNG、JPEG、WebP 或 GIF 图片")
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[mime]
    asset_id = str(uuid.uuid4())
    name = f"{notebook_id}-{asset_id}{extension}"
    staging_path = write_staged_image(asset_id, data)
    old_cover = db.get(NotebookCoverAsset, notebook_id)
    asset = Asset(
        id=asset_id, source_type="user_upload", media_type="image", mime_type=mime,
        extension=extension, original_name=(file.filename or "cover")[:255],
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
    book.cover_filename, book.cover_mime = name, mime
    try:
        db.commit()
    except Exception:
        db.rollback()
        staging_path.unlink(missing_ok=True)
        raise
    finalize_staged_image(db, asset)
    return {"cover_url": _cover_url(book)}

@router.get("/notebooks/{notebook_id}/cover")
def get_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None or book.cover_filename is None:
        raise HTTPException(404, "笔记封面不存在")
    cover = db.get(NotebookCoverAsset, notebook_id)
    asset = db.get(Asset, cover.asset_id) if cover else None
    try:
        owned = db.scalar(select(NotebookAsset.id).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset.id if asset is not None else False,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        )) if asset is not None else None
        path = storage_path(asset) if asset is not None and asset.state == "ready" and owned else None
    except AssetUnavailable:
        path = None
    if path is None:
        raise HTTPException(404, "笔记封面不存在")
    return FileResponse(path, media_type=asset.mime_type,
                        headers={"Cache-Control": "private, max-age=86400"})

@router.delete("/notebooks/{notebook_id}/cover", status_code=204)
def delete_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
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

@router.post("/courses/{course_id}/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_notebook_attachment(course_id: str, notebook_id: str,
                                     file: UploadFile = File(...),
                                     db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, notebook_id=notebook_id,
                                      filename=file.filename or "image", data=data)
    except AttachmentRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.commit()
    db.refresh(attachment)
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}

@router.post("/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_unbound_notebook_attachment(notebook_id: str,
                                             file: UploadFile = File(...),
                                             db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, notebook_id=notebook_id,
                                      filename=file.filename or "image", data=data)
    except AttachmentRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.commit()
    db.refresh(attachment)
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}

@router.get("/notebook-attachments/{attachment_id}")
def get_notebook_attachment(attachment_id: str, db: Session = Depends(get_db)):
    attachment = db.get(NotebookAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "附件不存在")
    if attachment.asset_id:
        try:
            owner = db.scalar(select(NotebookAsset).where(
                NotebookAsset.asset_id == attachment.asset_id,
                NotebookAsset.notebook_id == attachment.notebook_id,
                NotebookAsset.is_owner.is_(True),
            ))
            retained = bool(owner and db.scalar(select(func.count()).select_from(
                NotebookRevisionAsset
            ).where(
                NotebookRevisionAsset.notebook_id == attachment.notebook_id,
                NotebookRevisionAsset.asset_id == attachment.asset_id,
            )))
            if owner is None or (owner.detached_at is not None and not retained):
                raise AssetUnavailable("附件没有有效引用")
            asset = db.get(Asset, attachment.asset_id)
            if asset is None or asset.state != "ready":
                raise AssetUnavailable("附件资源不可用")
            path = storage_path(asset)
        except AssetUnavailable as exc:
            raise HTTPException(404, str(exc)) from exc
    else:
        try:
            path = attachment_path(attachment)
        except AttachmentRejected as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(404, "附件文件不存在")
    return FileResponse(path, media_type=attachment.mime,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})

@router.get("/assets/{asset_id}/content")
@router.get("/notebooks/{notebook_id}/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db),
):
    """Read a ready Notebook-owned asset using its stable resource ID.

    This local single-user app has no authenticated owner boundary; the owner
    link check enforces Notebook data integrity, not multi-user authorization.
    """
    if notebook_id is not None:
        notebook = db.get(Notebook, notebook_id)
        if notebook is None or notebook.deleted_at is not None:
            raise HTTPException(404, "笔记不存在")
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.is_owner.is_(True),
        ))
    else:
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ))
    if owner is None:
        raise HTTPException(404, "资源不存在")
    if notebook_id is None:
        notebook_id = owner.notebook_id
    asset = db.get(Asset, asset_id)
    if asset is None or asset.state != "ready":
        raise HTTPException(404, "资源不存在")
    if owner.detached_at is not None and not has_live_asset_references(db, asset, notebook_id):
        raise HTTPException(404, "资源已解除关联")
    try:
        path = storage_path(asset)
    except AssetUnavailable as exc:
        if "文件不存在" in str(exc):
            asset_row = db.get(Asset, asset_id)
            if asset_row is not None and asset_row.state == "ready":
                asset_row.state = "missing"
                db.commit()
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type=asset.mime_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})
