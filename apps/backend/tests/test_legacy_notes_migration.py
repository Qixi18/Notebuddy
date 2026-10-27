"""Legacy Note body migration: content, history, provenance, idempotency."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db.models import (
    KnowledgeNode,
    MaterialPage,
    Note,
    Notebook,
    NotebookBlockSource,
    NotebookDocumentRevision,
    NoteRevision,
    PageBlock,
    SourceRef,
)
from app.migration.legacy_notes import migrate
from app.notes.document import load_document
from tests.notebook_fixtures import make_asset, make_course, make_material, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]

MARKDOWN = """# 极限的定义

## 一句话概括
当 x 无限接近 a 时，f(x) 无限接近 L。

## 重点
- 左极限与右极限都存在且相等
- 极限与函数在该点的取值无关

公式：$\\lim_{x \\to a} f(x) = L$
"""


def _setup(session):
    course = make_course(session)
    book = make_notebook(session, course)
    book.document_json = (
        '{"schema_version":2,"doc":{"type":"doc","content":['
        '{"type":"paragraph","attrs":{"blockId":"existing-1"},'
        '"content":[{"type":"text","text":"用户已有正文，不能被覆盖"}]}]}}'
    )
    session.flush()
    asset = make_asset(session, book)
    material = make_material(session, book, asset)
    page = MaterialPage(
        material_id=material.id, page_number=1, raw_text="极限的定义 " * 30,
        parse_status="parsed",
    )
    session.add(page)
    session.flush()
    block = PageBlock(
        page_id=page.id, block_type="text", content="极限的定义 " * 30,
        position=0, extraction_method="native_text", confidence=1.0,
    )
    session.add(block)
    session.flush()
    from app.migration.document_backfill import backfill

    backfill(session)
    session.commit()

    node = KnowledgeNode(course_id=course.id, name="极限")
    session.add(node)
    session.flush()
    note = Note(
        course_id=course.id, notebook_id=book.id, knowledge_node_id=node.id,
        material_id=material.id, section_key="page:1", section_order=1,
        title="极限的定义", content_markdown=MARKDOWN, content_origin="ai",
    )
    session.add(note)
    session.flush()
    reference = SourceRef(
        page_block_id=block.id, source_type="course_material",
        quote="极限的定义", parser_version="phase2-1",
    )
    session.add(reference)
    session.flush()
    note.source_refs.append(reference)
    session.add_all([
        NoteRevision(
            note_id=note.id, revision_number=1, content_markdown=MARKDOWN,
            content_origin="ai", created_at=datetime(2026, 1, 1, 8, 0, 0),  # noqa: DTZ001
        ),
        NoteRevision(
            note_id=note.id, revision_number=2, content_markdown=MARKDOWN + "\n补充。",
            content_origin="user", created_at=datetime(2026, 2, 1, 9, 30, 0),  # noqa: DTZ001
        ),
    ])
    session.commit()
    return course, book, asset, material, note, reference


def test_dry_run_reports_without_writing(session):
    _course, book, _asset, _material, note, _ref = _setup(session)
    report = migrate(session, apply=False, batch_id="test-batch", backup=False)
    assert report["would_migrate"] == 1
    assert report["migrated"] == 0
    assert note.migrated_at is None
    assert session.query(NotebookDocumentRevision).filter_by(
        notebook_id=book.id, retention="pinned").count() == 0


def test_apply_migrates_body_history_and_sources(session):
    _course, book, _asset, _material, note, _ref = _setup(session)
    report = migrate(session, apply=True, batch_id="test-batch", backup=False)
    assert report["migrated"] == 1, report["notes"]
    assert report["history_snapshots"] == 2

    session.expire_all()
    note = session.get(Note, note.id)
    assert note.migrated_at is not None
    assert note.migration_batch == "test-batch"
    book = session.get(Notebook, book.id)
    content = load_document(book.document_json).content
    text = str(content)
    assert "用户已有正文，不能被覆盖" in text
    assert "旧笔记迁移" in text
    assert "极限的定义" in text
    assert "一句话概括" in text
    assert "左极限与右极限都存在且相等" in text

    pinned = list(session.scalars(select(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == book.id,
        NotebookDocumentRevision.retention == "pinned",
    )).all())
    assert len(pinned) == 2
    assert {row.legacy_created_at for row in pinned} == {
        datetime(2026, 1, 1, 8, 0, 0), datetime(2026, 2, 1, 9, 30, 0),  # noqa: DTZ001
    }
    assert all(row.revision < 0 for row in pinned)

    links = list(session.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == book.id)).all())
    assert links and links[0].block_id == f"source-{note.id}"


def test_migration_is_idempotent(session):
    _course, book, _asset, _material, _note, _ref = _setup(session)
    migrate(session, apply=True, batch_id="first", backup=False)
    session.expire_all()
    book = session.get(Notebook, book.id)
    revision = book.document_revision
    second = migrate(session, apply=True, batch_id="second", backup=False)
    session.expire_all()
    book = session.get(Notebook, book.id)
    assert second["migrated"] == 0
    assert second["candidates"] == 0
    assert book.document_revision == revision
