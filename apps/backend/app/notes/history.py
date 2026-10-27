"""Notebook document history snapshots."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    NotebookAsset,
    NotebookDocumentRevision,
    NotebookRevisionAsset,
    new_id,
    utc_now,
)
from app.notes.document import attachment_ids, dump_document

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
    # attachmentId is the stable Asset ID for backwards compatibility with
    # existing Tiptap image nodes. Only pin files owned by this Notebook.
    for asset_id in attachment_ids(content):
        owner_link_id = db.scalar(select(NotebookAsset.id).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.is_owner.is_(True),
        ))
        # A detached owner link may still be needed by a restored historical
        # document; pin the same ownership row instead of creating a new owner.
        if owner_link_id:
            db.add(NotebookRevisionAsset(
                id=new_id(), revision_id=snapshot.id, notebook_id=notebook_id,
                owner_link_id=owner_link_id, asset_id=asset_id,
            ))
    pinned_ids = set(db.scalars(select(NotebookRevisionAsset.asset_id).where(
        NotebookRevisionAsset.revision_id == snapshot.id,
    )).all())
    lowest = revision - MAX_SNAPSHOTS
    expired = NotebookDocumentRevision.created_at < now - timedelta(days=MAX_AGE_DAYS)
    excess = NotebookDocumentRevision.revision <= lowest
    db.execute(delete(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == notebook_id,
        or_(excess, expired),
    ).execution_options(synchronize_session=False))
    db.flush()
    still_pinned = set(db.scalars(select(NotebookRevisionAsset.asset_id).where(
        NotebookRevisionAsset.asset_id.in_(pinned_ids),
    )).all()) if pinned_ids else set()
    if still_pinned:
        for asset in db.scalars(select(Asset).where(
            Asset.id.in_(still_pinned), Asset.state == "delete_pending",
        )).all():
            asset.state = "ready"
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
