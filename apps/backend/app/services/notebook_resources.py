"""Notebook resource application use cases."""
from __future__ import annotations

import hashlib
import shutil
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookCoverAsset,
    NotebookRevisionAsset,
    utc_now,
)
from app.notes.assets import (
    AssetUnavailable,
    assert_notebook_asset,
    has_live_asset_references,
    remove_notebook_asset,
    storage_path,
)
from app.notes.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentRejected,
    attachment_path,
    sniff_image_mime,
    store_attachment,
)
from app.services.errors import ApplicationError
from app.services.image_assets import finalize_staged_image, write_staged_image
from app.services.resource_scopes import require_notebook


def restore_notebook_asset(db: Session, notebook_id: str, asset_id: str) -> tuple[Asset, str]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
    ))
    asset = db.get(Asset, asset_id)
    if owner is None or asset is None:
        raise ApplicationError(404, "这份资源不属于当前 Notebook")
    if owner.detached_at is None:
        return asset, owner.role
    if asset.state != "ready":
        raise ApplicationError(409, "资源文件已不可恢复，请重新上传原文件")
    active_owner = db.scalar(select(NotebookAsset.id).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if active_owner is not None:
        raise ApplicationError(409, "资源已归属其他位置，无法恢复到当前 Notebook")
    try:
        storage_path(asset)
    except AssetUnavailable as exc:
        raise ApplicationError(409, "资源文件缺失，无法恢复") from exc
    owner.detached_at = None
    db.commit()
    return asset, owner.role


def list_notebook_assets(db: Session, notebook_id: str, *, detached: bool = False):
    require_notebook(db, notebook_id)
    statement = select(Asset, NotebookAsset.role, NotebookAsset.notebook_id).join(
        NotebookAsset, NotebookAsset.asset_id == Asset.id,
    ).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.is_owner.is_(True),
    )
    if detached:
        statement = statement.where(
            NotebookAsset.detached_at.is_not(None), Asset.state == "ready",
        ).order_by(NotebookAsset.detached_at.desc())
    else:
        statement = statement.where(NotebookAsset.detached_at.is_(None)).order_by(
            NotebookAsset.created_at.desc(),
        )
    return list(db.execute(statement).all())


def mark_notebook_asset_inline(db: Session, notebook_id: str, asset_id: str) -> tuple[Asset, str]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    try:
        asset = assert_notebook_asset(db, asset_id, notebook_id)
    except AssetUnavailable as exc:
        raise ApplicationError(404, str(exc)) from exc
    if asset.media_type != "image":
        raise ApplicationError(422, "只有图片资源可以插入正文")
    link = db.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.role == "inline_image",
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
        NotebookAsset.asset_id == asset_id,
    ))
    if link is not None:
        return asset, "inline_image"

    inline_id = new_id()
    extension = asset.extension.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        extension = ".png"
    storage_key = f"notebooks/{notebook_id}/images/{inline_id}{extension}"
    target = (settings.data_dir / storage_key).resolve()
    base = (settings.data_dir / "notebooks" / notebook_id / "images").resolve()
    if not target.is_relative_to(base):
        raise ApplicationError(400, "图片存储路径不合法")
    try:
        source = storage_path(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except (AssetUnavailable, OSError) as exc:
        target.unlink(missing_ok=True)
        raise ApplicationError(409, "无法复制图片到笔记目录") from exc
    now = utc_now()
    inline_asset = Asset(
        id=inline_id, source_type="user_upload", media_type="image",
        mime_type=asset.mime_type, extension=extension,
        original_name=asset.original_name, storage_key=storage_key,
        byte_size=asset.byte_size, sha256=asset.sha256, state="ready",
        created_at=now, verified_at=now,
    )
    db.add_all([inline_asset, NotebookAsset(
        notebook_id=notebook_id, asset_id=inline_id, role="inline_image",
        is_owner=True, created_at=now,
    )])
    try:
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return inline_asset, "inline_image"


def delete_notebook_asset(db: Session, notebook_id: str, asset_id: str) -> str:
    if db.get(Notebook, notebook_id) is None:
        raise ApplicationError(404, "笔记不存在")
    try:
        return remove_notebook_asset(db, notebook_id, asset_id)
    except AssetUnavailable as exc:
        message = str(exc)
        raise ApplicationError(404 if "不存在" in message else 409, message) from exc


def create_notebook_attachment(
    db: Session, notebook_id: str, *, filename: str, data: bytes,
    course_id: str | None = None, unbound: bool = False,
) -> NotebookAttachment:
    require_notebook(db, notebook_id, course_id=course_id, unbound=unbound)
    try:
        attachment = store_attachment(
            db, notebook_id=notebook_id, filename=filename, data=data,
        )
        db.commit()
        db.refresh(attachment)
        return attachment
    except AttachmentRejected as exc:
        db.rollback()
        raise ApplicationError(exc.status_code, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def delete_notebook_cover(db: Session, notebook_id: str) -> None:
    book = db.get(Notebook, notebook_id)
    if book is None:
        raise ApplicationError(404, "笔记不存在")
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
        raise ApplicationError(404, "笔记不存在")
    mime = sniff_image_mime(data)
    if not data or len(data) > MAX_ATTACHMENT_BYTES or mime is None:
        raise ApplicationError(413 if len(data) > MAX_ATTACHMENT_BYTES else 422,
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


def get_notebook_cover(db: Session, notebook_id: str):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None or notebook.cover_filename is None:
        raise ApplicationError(404, "笔记封面不存在")
    cover = db.get(NotebookCoverAsset, notebook_id)
    asset = db.get(Asset, cover.asset_id) if cover else None
    owner = db.scalar(select(NotebookAsset.id).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.asset_id == asset.id if asset is not None else False,
        NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
    )) if asset is not None else None
    if asset is None or asset.state != "ready" or owner is None:
        raise ApplicationError(404, "笔记封面不存在")
    try:
        return storage_path(asset), asset.mime_type
    except AssetUnavailable as exc:
        raise ApplicationError(404, "笔记封面不存在") from exc


def get_notebook_attachment(db: Session, attachment_id: str):
    attachment = db.get(NotebookAttachment, attachment_id)
    if attachment is None:
        raise ApplicationError(404, "附件不存在")
    if attachment.asset_id:
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
            raise ApplicationError(404, "附件没有有效引用")
        asset = db.get(Asset, attachment.asset_id)
        if asset is None or asset.state != "ready":
            raise ApplicationError(404, "附件资源不可用")
        try:
            path = storage_path(asset)
        except AssetUnavailable as exc:
            raise ApplicationError(404, str(exc)) from exc
    else:
        try:
            path = attachment_path(attachment)
        except AttachmentRejected as exc:
            raise ApplicationError(exc.status_code, str(exc)) from exc
    if not path.is_file():
        raise ApplicationError(404, "附件文件不存在")
    return path, attachment.mime


def get_notebook_asset_content(
    db: Session, asset_id: str, notebook_id: str | None = None,
):
    if notebook_id is not None:
        require_notebook(db, notebook_id)
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
        raise ApplicationError(404, "资源不存在")
    notebook_id = notebook_id or owner.notebook_id
    asset = db.get(Asset, asset_id)
    if asset is None or asset.state != "ready":
        raise ApplicationError(404, "资源不存在")
    if owner.detached_at is not None and not has_live_asset_references(db, asset, notebook_id):
        raise ApplicationError(404, "资源已解除关联")
    try:
        path = storage_path(asset)
    except AssetUnavailable as exc:
        if "文件不存在" in str(exc):
            mark_asset_missing(db, asset_id)
        raise ApplicationError(404, str(exc)) from exc
    return path, asset.mime_type
