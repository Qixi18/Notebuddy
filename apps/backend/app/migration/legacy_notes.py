"""Migrate legacy ``Note.content_markdown`` into Notebook documents.

This is the only migration that moves user-authored body text.  Rules:

- the target is the Notebook the Note already belongs to (``Note.notebook_id``);
- the Note's leading H1 (when it matches the title) becomes the section heading
  and keeps the stable id ``source-<note_id>`` so old links remain meaningful;
- Notes are appended under an explicit "旧笔记迁移" chapter, so an existing
  Notebook body is never overwritten;
- every NoteRevision is copied as a pinned history snapshot with its original
  timestamp; restoring it restores the whole migrated document (safe), not a
  fragment;
- source relations are linked at section level when the legacy page block can
  be resolved; otherwise they are reported as unmapped, not dropped.

Run with ``--apply``; without it the command only reports what would change.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.checkpoint import create_checkpoint
from app.db.database import SessionLocal
from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    DocumentBlock,
    DocumentPage,
    Material,
    Note,
    Notebook,
    NotebookBlockSource,
    NotebookDocumentRevision,
    NoteRevision,
)
from app.document_processing.service import current_run
from app.notes.document import (
    dump_document,
    load_document,
    markdown_to_nodes,
    normalize_document,
)
from app.notes.store import DocumentConflict, write_document

MIGRATION_ORIGIN = "legacy_note_migration"
SECTION_CHAPTER_TITLE = "旧笔记迁移"
SECTION_CHAPTER_ID = "legacy-notes"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _note_nodes(note: Note) -> list[dict]:
    """Convert one Note into Tiptap nodes with a stable section heading."""

    body = markdown_to_nodes(note.content_markdown or "", block_id=f"source-{note.id}")
    heading = None
    if body and body[0].get("type") == "heading" and _normalize(
        _plain(body[0])
    ) == _normalize(note.title):
        heading = body.pop(0)
        heading.setdefault("attrs", {})["level"] = 2
    if heading is None:
        heading = {
            "type": "heading",
            "attrs": {"blockId": f"source-{note.id}", "level": 2},
            "content": [{"type": "text", "text": note.title}],
        }
    return [heading, *body]


def _plain(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    return "".join(_plain(child) for child in node.get("content") or [])


def _has_heading(nodes: list[dict], block_id: str) -> bool:
    return any((node.get("attrs") or {}).get("blockId") == block_id for node in nodes
               if isinstance(node, dict))


def _write_section_sources(
    db, notebook: Notebook, note: Note, body_block_id: str, report: dict,
) -> None:
    if note.material_id is None:
        return
    material = db.get(Material, note.material_id)
    if material is None:
        return
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_run(db, asset.id) if asset is not None else None
    if run is None:
        report["unmapped_sources"] += 1
        return
    page_numbers = sorted({ref.page_block.page.page_number for ref in note.source_refs
                           if ref.page_block is not None and ref.page_block.page is not None})
    if not page_numbers:
        return
    rows = db.execute(
        select(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(
            DocumentBlock.parse_run_id == run.id,
            DocumentPage.page_number.in_(page_numbers),
        )
    ).all()
    if not rows:
        report["unmapped_sources"] += len(note.source_refs)
        return
    for block, page_number in rows:
        exists = db.scalar(select(NotebookBlockSource.id).where(
            NotebookBlockSource.notebook_id == notebook.id,
            NotebookBlockSource.block_id == body_block_id,
            NotebookBlockSource.document_block_id == block.id,
        ))
        if exists:
            continue
        db.add(NotebookBlockSource(
            notebook_id=notebook.id, block_id=body_block_id,
            generation_job_id=None, parse_run_id=run.id, document_block_id=block.id,
            page_number=page_number, confidence=block.confidence, status="active",
            created_at=_now(),
        ))
    db.flush()


def _snapshot_history(db, notebook: Notebook, notes: list[Note], final_document: dict,
                      report: dict) -> None:
    note_ids = [note.id for note in notes]
    revisions = list(db.scalars(
        select(NoteRevision).where(NoteRevision.note_id.in_(note_ids))
        .order_by(NoteRevision.created_at, NoteRevision.id)
    ).all()) if note_ids else []
    existing = set(db.scalars(select(NotebookDocumentRevision.revision).where(
        NotebookDocumentRevision.notebook_id == notebook.id,
        NotebookDocumentRevision.retention == "pinned",
    )).all())
    index = 0
    for revision in revisions:
        index += 1
        number = -index
        if number in existing:
            continue
        db.add(NotebookDocumentRevision(
            id=new_id(), notebook_id=notebook.id, revision=number, schema_version=2,
            document_json=dump_document(normalize_document(final_document)),
            origin=MIGRATION_ORIGIN, legacy_created_at=revision.created_at,
            retention="pinned", created_at=_now(),
        ))
        report["history_snapshots"] += 1
    db.flush()


def migrate(
    db, *, apply: bool, batch_id: str, limit: int | None = None, backup: bool = True,
) -> dict:
    query = (
        select(Note)
        .where(Note.content_markdown != "", Note.migrated_at.is_(None))
        .order_by(Note.notebook_id, Note.section_order, Note.created_at, Note.id)
    )
    if limit:
        query = query.limit(limit)
    notes = list(db.scalars(query).all())
    report: dict = {
        "apply": apply,
        "batch_id": batch_id,
        "candidates": len(notes),
        "notes": [],
        "notebooks": {},
        "history_snapshots": 0,
        "unmapped_sources": 0,
        "failed": 0,
        "skipped": Counter(),
        "backup": None,
    }
    if apply and backup:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        checkpoint = create_checkpoint(
            settings.data_dir, settings.backups_dir / f"pre-legacy-notes-{stamp}")
        report["backup"] = str(checkpoint)

    by_notebook: dict[str, list[Note]] = {}
    for note in notes:
        if not note.notebook_id:
            report["skipped"]["no_notebook"] += 1
            report["notes"].append({"note_id": note.id, "status": "skipped_no_notebook"})
            continue
        notebook = db.get(Notebook, note.notebook_id)
        if notebook is None or notebook.deleted_at is not None:
            report["skipped"]["notebook_missing"] += 1
            report["notes"].append({"note_id": note.id, "status": "skipped_notebook_missing"})
            continue
        by_notebook.setdefault(note.notebook_id, []).append(note)

    for notebook_id, notebook_notes in by_notebook.items():
        notebook = db.get(Notebook, notebook_id)
        assert notebook is not None
        stored = load_document(notebook.document_json)
        nodes = list(stored.content.get("content") or [])
        already = [note for note in notebook_notes
                   if _has_heading(nodes, f"source-{note.id}")]
        pending = [note for note in notebook_notes if note not in already]
        added = 0
        for note in already:
            if apply:
                note.migrated_at = _now()
                note.migrated_revision = notebook.document_revision
                note.migration_batch = batch_id
            report["notes"].append({"note_id": note.id, "status": "already_present",
                                    "chars": len(note.content_markdown or "")})
        if pending and not _has_heading(nodes, SECTION_CHAPTER_ID):
            nodes.append({
                "type": "heading",
                "attrs": {"blockId": SECTION_CHAPTER_ID, "level": 1},
                "content": [{"type": "text", "text": SECTION_CHAPTER_TITLE}],
            })
        for note in pending:
            nodes.extend(_note_nodes(note))
            added += 1
        next_revision = notebook.document_revision
        if pending and apply:
            try:
                next_revision, final = write_document(
                    db, notebook,
                    {"type": "doc", "content": nodes},
                    expected_revision=notebook.document_revision,
                    origin=MIGRATION_ORIGIN,
                )
            except DocumentConflict as exc:
                report["failed"] += len(pending)
                for note in pending:
                    report["notes"].append({"note_id": note.id, "status": "conflict",
                                            "error": str(exc)})
                db.rollback()
                continue
            for note in pending:
                note.migrated_at = _now()
                note.migrated_revision = next_revision
                note.migration_batch = batch_id
                _write_section_sources(db, notebook, note, f"source-{note.id}", report)
                report["notes"].append({
                    "note_id": note.id, "status": "migrated",
                    "chars": len(note.content_markdown or ""),
                    "notebook_id": notebook.id, "revision": next_revision,
                })
            _snapshot_history(db, notebook, pending, final, report)
            db.commit()
        elif pending:
            for note in pending:
                report["notes"].append({"note_id": note.id, "status": "would_migrate",
                                        "chars": len(note.content_markdown or "")})
        else:
            db.commit()
        report["notebooks"][notebook.id] = {
            "title": notebook.title, "migrated": added, "already": len(already),
            "revision": next_revision,
        }

    report["skipped"] = dict(report["skipped"])
    report["migrated"] = sum(1 for item in report["notes"] if item["status"] == "migrated")
    report["would_migrate"] = sum(1 for item in report["notes"]
                                  if item["status"] == "would_migrate")
    report["already_present"] = sum(1 for item in report["notes"]
                                    if item["status"] == "already_present")
    report["characters"] = sum(item.get("chars", 0) for item in report["notes"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy Note bodies into Notebook documents")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--batch", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    batch_id = args.batch or f"legacy-notes-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    with SessionLocal() as db:
        report = migrate(
            db, apply=args.apply, batch_id=batch_id, limit=args.limit,
            backup=not args.no_backup,
        )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
