"""Notebook image attachments: validated storage outside the course-material pipeline."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import Notebook, NotebookAttachment, NotebookDocumentRevision, utc_now
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


def attachment_directory(notebook_id: str) -> Path:
    return settings.data_dir / "notebook-attachments" / notebook_id


def public_url(attachment_id: str) -> str:
    return f"/api/v1/notebook-attachments/{attachment_id}"


def store_attachment(db, *, course_id: str, notebook_id: str, filename: str,
                     data: bytes) -> NotebookAttachment:
    if not data:
        raise AttachmentRejected("图片内容为空")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentRejected("图片不能超过 10 MB", status_code=413)
    mime = sniff_image_mime(data)
    if mime is None:
        raise AttachmentRejected("只支持 PNG、JPEG、WebP 或 GIF 图片")
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
        course_id=course_id,
        original_filename=(filename or "image")[:255],
        stored_filename=stored_name,
        mime=mime,
        size_bytes=len(data),
        created_at=utc_now(),
    )
    try:
        db.add(attachment)
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
        try:
            attachment_path(attachment).unlink(missing_ok=True)
        except (OSError, AttachmentRejected):
            continue
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
        for path in files:
            path.unlink()
        directory.rmdir()
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
