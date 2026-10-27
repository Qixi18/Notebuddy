"""Evidence persistence and answer citations for Document IR + Notebook body."""

from __future__ import annotations

import pytest

from app.ai.evidence import extract_claims
from app.db.models import Conversation, DocumentParseRun
from app.notes.document import normalize_document
from app.notes.store import write_document
from app.retrieval.service import build_context, retrieve
from app.services.assistant_sources import sources_from_evidence, sources_from_results
from app.services.conversations import persist_assistant_message
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_material,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


def _setup(session):
    course = make_course(session, "数学")
    book = make_notebook(session, course, "极限笔记")
    asset = make_asset(session, book, name="limits.pdf")
    material = make_material(session, book, asset)
    persist_ir(session, book, asset)
    write_document(session, book, normalize_document({
        "type": "doc",
        "content": [{
            "type": "heading", "attrs": {"level": 1, "blockId": "h-1"},
            "content": [{"type": "text", "text": "第一章 极限"}],
        }, {
            "type": "paragraph", "attrs": {"blockId": "p-1"},
            "content": [{"type": "text",
                         "text": "极限描述函数在一点附近的变化趋势，是连续与导数的基础。"}],
        }],
    }), expected_revision=0, origin="autosave")
    session.commit()
    return course, book, asset, material


def test_two_path_retrieval_returns_traceable_results(session):
    course, _book, asset, material = _setup(session)
    chunks = retrieve(session, course_id=course.id, question="极限 变化趋势", limit=8)
    kinds = {chunk.kind for chunk in chunks}
    assert "document" in kinds
    assert "notebook" in kinds
    document_chunk = next(chunk for chunk in chunks if chunk.kind == "document")
    assert document_chunk.material_id == material.id
    assert document_chunk.asset_id == asset.id
    assert document_chunk.parse_run_id
    assert document_chunk.document_block_ids
    assert document_chunk.page_numbers == (1,)
    notebook_chunk = next(chunk for chunk in chunks if chunk.kind == "notebook")
    assert notebook_chunk.notebook_id
    assert notebook_chunk.block_id
    assert notebook_chunk.notebook_revision >= 1
    context = build_context(chunks)
    assert "[课程资料：" in context
    assert "[课程笔记：" in context


def test_persisted_evidence_restores_notebook_sources(session):
    course, book, asset, _material = _setup(session)
    conversation = Conversation(course_id=course.id, title="测试会话")
    session.add(conversation)
    session.flush()
    chunks = retrieve(session, course_id=course.id, question="极限", limit=4)
    assert chunks
    assistant = persist_assistant_message(
        session, conversation=conversation, learning_goal="理解概念",
        content="极限是连续的基础。[课程笔记：极限笔记 | 第 1 节]",
        model_version="test-model",
        chunks=chunks, web_results=[],
        claims=[{"claim_key": "answer", "chunk_indexes": list(range(len(chunks))),
                 "web_indexes": []}],
    )
    evidence = assistant.evidence
    assert evidence
    assert any(item.notebook_id or item.document_block_id for item in evidence)
    sources = sources_from_evidence(session, assistant)
    assert sources
    assert any(source["source_type"] in {"notebook", "course_material"} for source in sources)
    assert any(source.get("snippet") for source in sources)
    material_source = next(source for source in sources if source["source_type"] == "course_material")
    assert material_source["source_status"] == "active"
    assert material_source["document_block_ids"]
    assert material_source["page_numbers"]
    notebook_source = next(source for source in sources if source["source_type"] == "notebook")
    assert notebook_source["source_status"] == "active"
    live = sources_from_results(chunks, [])
    assert any(source.get("notebook_id") for source in live)
    assert all(source["source_status"] == "active" for source in live)

    run = session.get(DocumentParseRun, material_source["parse_run_id"])
    assert run is not None
    run.is_current = False
    session.flush()
    stale_sources = sources_from_evidence(session, assistant)
    stale_material_source = next(source for source in stale_sources if source["source_type"] == "course_material")
    assert stale_material_source["source_status"] == "stale"

    book.document_revision += 1
    session.flush()
    stale_notebook_source = next(source for source in sources_from_evidence(session, assistant)
                                 if source["source_type"] == "notebook")
    assert stale_notebook_source["source_status"] == "stale"

    asset.state = "missing"
    session.flush()
    unavailable_material_source = next(source for source in sources_from_evidence(session, assistant)
                                       if source["source_type"] == "course_material")
    assert unavailable_material_source["source_status"] == "unavailable"


def test_notebook_citation_marker_maps_to_chunk(session):
    course, _book, _asset, _material = _setup(session)
    chunks = [chunk for chunk in retrieve(
        session, course_id=course.id, question="极限", limit=8) if chunk.kind == "notebook"]
    assert chunks
    section = chunks[0].location_label
    claims = extract_claims(
        f"结论。[课程笔记：极限笔记 | {section}]",
        chunks, [],
    )
    assert claims[0].chunk_indexes == (0,)
    assert claims[0].evidence_type.startswith("course")


def test_material_filter_excludes_notebook_chunks(session):
    course, _book, _asset, material = _setup(session)
    chunks = retrieve(session, course_id=course.id, question="极限", material_id=material.id, limit=8)
    assert chunks
    assert all(chunk.kind == "document" for chunk in chunks)
    assert all(chunk.material_id == material.id for chunk in chunks)


def test_multilocation_chunk_does_not_claim_first_page_or_block(session):
    course, _book, _asset, _material = _setup(session)
    from app.db.models import DocumentChunk

    chunk = session.query(DocumentChunk).first()
    chunk.page_numbers_json = '[1, 2]'
    chunk.block_ids_json = '["block-a", "block-b"]'
    session.commit()

    result = next(item for item in retrieve(session, course_id=course.id,
                                            question="极限", limit=8)
                  if item.kind == "document")
    assert result.page_number == 0
    assert result.document_block_id is None
    assert result.page_numbers == (1, 2)
    assert result.document_block_ids == ("block-a", "block-b")
    assert result.location_label == "跨页片段"


def test_document_source_endpoint_enforces_notebook_ownership(session):
    from fastapi import HTTPException

    from app.api.v1.materials import get_asset_document

    _course, book, asset, _material = _setup(session)
    foreign_course = make_course(session, "另一个课程")
    foreign_book = make_notebook(session, foreign_course, "其他笔记")
    with pytest.raises(HTTPException) as captured:
        get_asset_document(asset.id, notebook_id=foreign_book.id, db=session)
    assert captured.value.status_code == 404

    assert book.id != foreign_book.id
