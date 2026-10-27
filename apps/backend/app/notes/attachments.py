"""Notebook image attachments: validated storage outside the course-material pipeline."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookDocumentRevision,
    utc_now,
)
from app.notes.assets import has_live_asset_references
from app.notes.document import attachment_ids, load_document

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ORPHAN_GRACE_PERIOD = timedelta(days=1)
STORED_IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|webp|gif)$")
ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 12_000


class AttachmentRejected(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_dimensions(data: bytes, mime: str) -> tuple[int, int]:
    """Read dimensions from image headers without decoding pixel buffers."""
    width = height = 0
    if mime == "image/png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ValueError("PNG 头信息不完整")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
    elif mime == "image/jpeg":
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            raise ValueError("JPEG 头信息不完整")
        offset = 2
        frame_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while offset < len(data):
            if data[offset] != 0xFF:
                raise ValueError("JPEG 标记序列无效")
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in {0x01, *range(0xD0, 0xD9)}:
                continue
            if marker == 0xDA:
                break
            if offset + 2 > len(data):
                break
            segment_length = int.from_bytes(data[offset:offset + 2], "big")
            if segment_length < 2 or offset + segment_length > len(data):
                raise ValueError("JPEG 段长度无效")
            if marker in frame_markers:
                if segment_length < 7:
                    raise ValueError("JPEG 帧头不完整")
                height = int.from_bytes(data[offset + 3:offset + 5], "big")
                width = int.from_bytes(data[offset + 5:offset + 7], "big")
                break
            offset += segment_length
    elif mime == "image/gif":
        if len(data) < 10 or data[:6] not in {b"GIF87a", b"GIF89a"}:
            raise ValueError("GIF 头信息不完整")
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
    elif mime == "image/webp":
        if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("WebP 头信息不完整")
        declared_size = int.from_bytes(data[4:8], "little") + 8
        if declared_size > len(data):
            raise ValueError("WebP 数据不完整")
        offset = 12
        while offset + 8 <= declared_size:
            chunk_type = data[offset:offset + 4]
            chunk_size = int.from_bytes(data[offset + 4:offset + 8], "little")
            start = offset + 8
            end = start + chunk_size
            if end > declared_size:
                raise ValueError("WebP 分块长度无效")
            chunk = data[start:end]
            if chunk_type == b"VP8X" and len(chunk) >= 10:
                width = 1 + int.from_bytes(chunk[4:7], "little")
                height = 1 + int.from_bytes(chunk[7:10], "little")
                break
            if chunk_type == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(chunk[6:8], "little") & 0x3FFF
                height = int.from_bytes(chunk[8:10], "little") & 0x3FFF
                break
            if chunk_type == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
                bits = int.from_bytes(chunk[1:5], "little")
                width = 1 + (bits & 0x3FFF)
                height = 1 + ((bits >> 14) & 0x3FFF)
                break
            offset = end + (chunk_size & 1)
    else:
        raise ValueError("不支持的图片格式")

    if width < 1 or height < 1:
        raise ValueError("无法读取图片尺寸")
    if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE or width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"图片尺寸超出限制（单边最多 {MAX_IMAGE_EDGE} 像素，总像素最多 {MAX_IMAGE_PIXELS:,}）")
    return width, height


def attachment_directory(notebook_id: str) -> Path:
    return settings.data_dir / "notebook-attachments" / notebook_id


def public_url(attachment_id: str) -> str:
    return f"/api/v1/notebook-attachments/{attachment_id}"


def store_attachment(db, *, notebook_id: str, filename: str,
                     data: bytes) -> NotebookAttachment:
    if not data:
        raise AttachmentRejected("图片内容为空")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentRejected("图片不能超过 10 MB", status_code=413)
    mime = sniff_image_mime(data)
    if mime is None:
        raise AttachmentRejected("只支持 PNG、JPEG、WebP 或 GIF 图片")
    try:
        image_dimensions(data, mime)
    except ValueError as exc:
        raise AttachmentRejected(str(exc)) from exc
    directory = attachment_directory(notebook_id)
    base = (settings.data_dir / "notebook-attachments").resolve()
    resolved = directory.resolve()
    if not resolved.is_relative_to(base):
        raise AttachmentRejected("附件存储路径不合法", status_code=400)
    directory.mkdir(parents=True, exist_ok=True)
    extension = ALLOWED_MIME[mime]
    stored_name = f"{uuid.uuid4().hex}{extension}"
    stored_path = directory / stored_name
    stored_path.write_bytes(data)
    attachment = NotebookAttachment(
        id=new_id(),
        notebook_id=notebook_id,
        original_filename=(filename or "image")[:255],
        stored_filename=stored_name,
        mime=mime,
        size_bytes=len(data),
        created_at=utc_now(),
    )
    asset = Asset(
        id=attachment.id,
        source_type="user_upload",
        media_type="image",
        mime_type=mime,
        extension=extension,
        original_name=attachment.original_filename,
        storage_key=f"notebook-attachments/{notebook_id}/{stored_name}",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        state="ready",
        created_at=attachment.created_at,
        verified_at=attachment.created_at,
    )
    attachment.asset_id = asset.id
    try:
        db.add_all([
            asset,
            attachment,
            NotebookAsset(
                notebook_id=notebook_id, asset_id=asset.id, role="inline_image",
                is_owner=True, created_at=attachment.created_at,
            ),
        ])
        db.flush()
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    return attachment


def attachment_path(attachment: NotebookAttachment) -> Path:
    base = (settings.data_dir / "notebook-attachments").resolve()
    path = (base / attachment.notebook_id / attachment.stored_filename).resolve()
    if not path.is_relative_to(base):
        raise AttachmentRejected("附件路径不合法", status_code=400)
    return path


def prune_unreferenced_attachments(db: Session, *, limit: int = 100) -> int:
    """Remove aged uploads only when neither the current document nor history uses them."""

    cutoff = utc_now() - ORPHAN_GRACE_PERIOD
    candidates = db.scalars(select(NotebookAttachment).where(
        NotebookAttachment.created_at < cutoff,
    ).order_by(NotebookAttachment.created_at, NotebookAttachment.id)).all()
    references: dict[str, set[str] | None] = {}
    removed = 0
    for attachment in candidates:
        if attachment.notebook_id not in references:
            book = db.get(Notebook, attachment.notebook_id)
            if book is None:
                references[attachment.notebook_id] = set()
            else:
                current = load_document(book.document_json)
                if current.warning:
                    references[attachment.notebook_id] = None
                else:
                    used = attachment_ids(current.content)
                    snapshots = db.scalars(select(NotebookDocumentRevision.document_json).where(
                        NotebookDocumentRevision.notebook_id == attachment.notebook_id,
                    )).all()
                    for raw in snapshots:
                        stored = load_document(raw)
                        if stored.warning:
                            used = None
                            break
                        used.update(attachment_ids(stored.content))
                    references[attachment.notebook_id] = used
        used = references[attachment.notebook_id]
        if used is None or attachment.id in used:
            continue
        asset = db.get(Asset, attachment.asset_id) if attachment.asset_id else None
        if asset is not None:
            if has_live_asset_references(db, asset, attachment.notebook_id):
                continue
            asset.state = "delete_pending"
            db.commit()
        try:
            attachment_path(attachment).unlink(missing_ok=True)
        except (OSError, AttachmentRejected):
            continue
        if asset is not None:
            db.execute(delete(NotebookAsset).where(NotebookAsset.asset_id == asset.id))
            db.delete(asset)
        db.delete(attachment)
        removed += 1
        if removed >= limit:
            break
    if removed:
        db.commit()
    return removed


def prune_deleted_notebook_directories(db: Session, *, limit: int = 20) -> int:
    """Remove old attachment directories left after notebook/course cascade deletes."""

    base = (settings.data_dir / "notebook-attachments").resolve()
    if not base.is_dir():
        return 0
    cutoff = (utc_now() - ORPHAN_GRACE_PERIOD).timestamp()
    removed = 0
    for directory in base.iterdir():
        if not directory.is_dir() or directory.is_symlink() or directory.resolve().parent != base:
            continue
        try:
            uuid.UUID(directory.name)
        except ValueError:
            continue
        if db.get(Notebook, directory.name) is not None:
            continue
        files = list(directory.iterdir())
        if any(item.is_symlink() or not item.is_file() or not STORED_IMAGE_NAME.fullmatch(item.name)
               or item.resolve().parent != directory
               or item.stat().st_mtime >= cutoff for item in files):
            continue
        prefix = f"notebook-attachments/{directory.name}/"
        assets = db.scalars(select(Asset).where(Asset.storage_key.like(f"{prefix}%"))).all()
        # A removed Notebook can still have retained history/job references if
        # foreign-key cascades were not enforced by an older database. Do not
        # unlink any file in the directory until every Asset is unreferenced.
        if any(has_live_asset_references(db, asset, directory.name) for asset in assets):
            continue
        for asset in assets:
            if asset.state == "ready":
                asset.state = "delete_pending"
            db.execute(delete(NotebookAsset).where(NotebookAsset.asset_id == asset.id))
        if assets:
            db.commit()
        for path in files:
            path.unlink()
        directory.rmdir()
        for asset in assets:
            if asset.state == "delete_pending":
                db.delete(asset)
        if assets:
            db.commit()
        removed += 1
        if removed >= limit:
            break
    return removed


def prune_stray_attachment_files(db: Session, *, limit: int = 100) -> int:
    """Remove aged files without a database row, e.g. after an interrupted upload."""

    base = (settings.data_dir / "notebook-attachments").resolve()
    if not base.is_dir():
        return 0
    cutoff = (utc_now() - ORPHAN_GRACE_PERIOD).timestamp()
    removed = 0
    for directory in base.iterdir():
        if not directory.is_dir() or directory.is_symlink() or directory.resolve().parent != base:
            continue
        try:
            uuid.UUID(directory.name)
        except ValueError:
            continue
        if db.get(Notebook, directory.name) is None:
            continue  # The deleted-notebook sweep handles this directory.
        known = set(db.scalars(select(NotebookAttachment.stored_filename).where(
            NotebookAttachment.notebook_id == directory.name,
        )).all())
        for path in directory.iterdir():
            if (path.name in known or not STORED_IMAGE_NAME.fullmatch(path.name)
                    or path.is_symlink() or not path.is_file() or path.resolve().parent != directory
                    or path.stat().st_mtime >= cutoff):
                continue
            path.unlink()
            removed += 1
            if removed >= limit:
                return removed
    return removed
