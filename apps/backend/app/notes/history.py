"""Notebook document history snapshots."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import NotebookDocumentRevision, utc_now
from app.notes.document import dump_document

MAX_SNAPSHOTS = 100
MAX_AGE_DAYS = 90


def record_snapshot(db: Session, notebook_id: str, revision: int, content: dict,
                    *, origin: str = "autosave") -> NotebookDocumentRevision:
    """Write a snapshot inside the caller's transaction, then trim old ones.

    Keep at most ``MAX_SNAPSHOTS`` revisions and no snapshot older than
    ``MAX_AGE_DAYS``. A burst of autosaves must not grow the table unbounded.
    """

    now = utc_now()
    snapshot = NotebookDocumentRevision(
        notebook_id=notebook_id,
        revision=revision,
        schema_version=2,
        document_json=dump_document(content),
        origin=origin,
        created_at=now,
    )
    db.add(snapshot)
    db.flush()
    lowest = revision - MAX_SNAPSHOTS
    expired = NotebookDocumentRevision.created_at < now - timedelta(days=MAX_AGE_DAYS)
    excess = NotebookDocumentRevision.revision <= lowest
    db.execute(delete(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == notebook_id,
        or_(excess, expired),
    ).execution_options(synchronize_session=False))
    return snapshot


def list_snapshots(db: Session, notebook_id: str, *, limit: int = 100) -> list[NotebookDocumentRevision]:
    return list(db.scalars(select(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == notebook_id
    ).order_by(NotebookDocumentRevision.revision.desc()).limit(limit)).all())


def get_snapshot(db: Session, notebook_id: str, revision: int) -> NotebookDocumentRevision | None:
    return db.scalar(select(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == notebook_id,
        NotebookDocumentRevision.revision == revision,
    ))
