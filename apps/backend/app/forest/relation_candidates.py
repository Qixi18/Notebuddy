"""Rebuildable relation candidates from current Notebook body sections only."""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select

from app.db.models import Course, Notebook
from app.forest.service import section_relation_fingerprint
from app.notes.document import load_document
from app.notes.index import build_sections


def _tokens(value: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9]+", value.casefold()))
    for group in re.findall(r"[\u4e00-\u9fff]+", value):
        words.update(group[index:index + 2] for index in range(max(1, len(group) - 1)))
    return words


def body_sections(db, *, full: bool = False) -> list[dict]:
    rows = db.execute(select(Notebook, Course.name).join(Course, Course.id == Notebook.course_id)
                      .where(Notebook.deleted_at.is_(None), Course.deleted_at.is_(None))
                      .order_by(Notebook.id)).all()
    result = []
    for book, course_name in rows:
        stored = load_document(book.document_json)
        if stored.warning:
            continue
        for section in build_sections(stored.content):
            if not section.heading.strip() and not section.text.strip():
                continue
            result.append({
                "notebook_id": book.id, "course_id": book.course_id,
                "course_name": course_name, "notebook_title": book.title,
                "block_id": section.block_id, "title": section.heading or book.title,
                "excerpt": section.text if full else section.text[:1200], "revision": book.document_revision,
                "fingerprint": section_relation_fingerprint(section.heading, section.text),
            })
    return result


def candidate_snapshots(db, course_id: str, *, notebook_id: str | None = None,
                        processing_route: str = 'standard') -> dict:
    rows = body_sections(db, full=processing_route == 'llm')
    source = [row for row in rows if row["course_id"] == course_id
              and (notebook_id is None or row["notebook_id"] == notebook_id)]
    target = [row for row in rows if row["course_id"] != course_id]
    if processing_route == 'llm':
        for prefix, group in (('s', source), ('t', target)):
            for index, row in enumerate(group):
                row['key'] = f'{prefix}{index}'
        return {'sources': source, 'targets': target, 'processing_route': 'llm'}
    # Candidate ranking is a bounded model input, never a substitute body.
    # Its complete chosen identities/fingerprints are persisted with the job.
    terms = set().union(*(_tokens(row["title"]) for row in target)) if target else set()
    source.sort(key=lambda row: (-len(_tokens(row["title"]) & terms), row["notebook_id"], row["block_id"]))
    source = source[:24]
    own_terms = set().union(*(_tokens(row["title"]) for row in source)) if source else set()
    target.sort(key=lambda row: (-len(_tokens(row["title"]) & own_terms), row["notebook_id"], row["block_id"]))
    target = target[:24]
    for prefix, group in (("s", source), ("t", target)):
        for index, row in enumerate(group):
            row["key"] = f"{prefix}{index}"
    return {"sources": source, "targets": target}


def snapshot_fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
