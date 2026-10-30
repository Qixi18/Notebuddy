"""The single write path for ``Notebook.document_json``.

Every mutation (user save, AI merge, history restore, migration) goes through
:func:`write_document` so the revision CAS, snapshot, derived section index and
source-relation hygiene can never diverge.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Notebook, NotebookBlockSource
from app.notes.document import (
    DocumentValidationError,
    dump_document,
    load_document,
    normalize_document,
    validate_document,
)
from app.notes.history import record_snapshot
from app.notes.index import rebuild_notebook_sections


class DocumentConflict(RuntimeError):
    """The document changed since the caller's expected revision."""


class DocumentTooLarge(DocumentValidationError):
    pass


def write_document(
    db: Session,
    notebook: Notebook,
    content: Any,
    *,
    expected_revision: int,
    origin: str = "autosave",
    legacy_compatible: bool = False,
    refresh_relations: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Validate, CAS-write, snapshot and re-index one document mutation."""

    normalized = validate_document(normalize_document(content))
    previous = load_document(notebook.document_json).content
    body_changed = normalized != previous
    next_revision = expected_revision + 1
    now = datetime.now(UTC).replace(tzinfo=None)
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook.id,
        Notebook.document_revision == expected_revision,
        Notebook.deleted_at.is_(None),
    ).values(
        document_json=dump_document(normalized, legacy_compatible=legacy_compatible),
        document_revision=next_revision,
        updated_at=now,
    ))
    if result.rowcount != 1:
        raise DocumentConflict("笔记正文已被其他编辑更新，请刷新后再保存")
    notebook.document_revision = next_revision
    record_snapshot(db, notebook.id, next_revision, normalized, origin=origin)
    rebuild_notebook_sections(db, notebook, normalized, next_revision)
    mark_orphaned_sources_stale(db, notebook.id, normalized, previous_content=previous)
    db.flush()
    if refresh_relations and body_changed and notebook.course_id is not None:
        # Keep Forest's automatic cross-course relation candidates in step with
        # the canonical Notebook body. Generation and explicit forest actions
        # may enqueue the same snapshot; the job idempotency key coalesces them.
        from app.forest.notebook_relations import enqueue_notebook_relations

        enqueue_notebook_relations(db, notebook.course_id, notebook_id=notebook.id)
    return next_revision, normalized


def body_fingerprint(node: dict[str, Any]) -> str:
    """A relation supports this exact block content, including nested structure."""

    return hashlib.sha256(json.dumps(
        node, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _body_fingerprints(content: dict[str, Any]) -> dict[str, str]:
    fingerprints: dict[str, str] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        attrs = node.get("attrs") or {}
        block_id = attrs.get("blockId")
        if isinstance(block_id, str):
            fingerprints[block_id] = body_fingerprint(node)
        for child in node.get("content") or []:
            walk(child)

    walk(content)
    return fingerprints


def mark_orphaned_sources_stale(
    db: Session, notebook_id: str, content: dict[str, Any],
    *, previous_content: dict[str, Any] | None = None,
) -> int:
    """Invalidate rewritten blocks; reactivate only exact restored content.

    Stable IDs alone cannot prove an edited formula still matches its source.
    Legacy active rows get a fingerprint from the pre-save body, never from
    the replacement body. Unknown stale rows stay stale until reviewed.
    """

    current = _body_fingerprints(content)
    previous = _body_fingerprints(previous_content or {})
    rows = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == notebook_id,
        NotebookBlockSource.status.in_(("active", "stale")),
    )).all())
    changed = 0
    for row in rows:
        if row.body_fingerprint is None and row.status == "active":
            row.body_fingerprint = previous.get(row.block_id)
        status = "active" if (
            row.body_fingerprint is not None
            and current.get(row.block_id) == row.body_fingerprint
        ) else "stale"
        if row.status != status:
            row.status = status
            changed += 1
    if changed:
        db.flush()
    return changed


def block_source_payload(db: Session, notebook_id: str, block_id: str) -> list[dict]:
    from app.db.models import Asset, DocumentBlock, DocumentParseRun

    rows = db.execute(
        select(NotebookBlockSource, DocumentBlock, DocumentParseRun, Asset)
        .join(DocumentBlock, DocumentBlock.id == NotebookBlockSource.document_block_id)
        .join(DocumentParseRun, DocumentParseRun.id == NotebookBlockSource.parse_run_id)
        .join(Asset, Asset.id == DocumentParseRun.asset_id)
        .where(
            NotebookBlockSource.notebook_id == notebook_id,
            NotebookBlockSource.block_id == block_id,
        )
        .order_by(NotebookBlockSource.created_at)
    ).all()
    payload: list[dict] = []
    for link, block, run, asset in rows:
        payload.append({
            "block_id": link.block_id,
            "document_block_id": block.block_id,
            "parse_run_id": run.id,
            "parse_version": run.parser_version,
            "asset_id": asset.id,
            "asset_name": asset.original_name,
            "page_number": link.page_number,
            "location_label": f"第 {link.page_number} 页",
            "quote": block.text[:400],
            "block_type": block.block_type,
            "confidence": link.confidence,
            "status": link.status,
            "generation_job_id": link.generation_job_id,
            "body_fingerprint": link.body_fingerprint,
        })
    return payload
