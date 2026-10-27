"""Evidence persistence and answer citations for Document IR + Notebook body."""

from __future__ import annotations

from app.ai.evidence import extract_claims
from app.db.models import Conversation
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
    make_material(session, book, asset)
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
    return course, book, asset


def test_two_path_retrieval_returns_traceable_results(session):
    course, _book, asset = _setup(session)
    chunks = retrieve(session, course_id=course.id, question="极限 变化趋势", limit=8)
    kinds = {chunk.kind for chunk in chunks}
    assert "document" in kinds
    assert "notebook" in kinds
    document_chunk = next(chunk for chunk in chunks if chunk.kind == "document")
    assert document_chunk.material_id == asset.id
    assert document_chunk.parse_run_id
    assert document_chunk.document_block_id
    notebook_chunk = next(chunk for chunk in chunks if chunk.kind == "notebook")
    assert notebook_chunk.notebook_id
    assert notebook_chunk.block_id
    assert notebook_chunk.notebook_revision >= 1
    context = build_context(chunks)
    assert "[课程资料：" in context
    assert "[课程笔记：" in context


def test_persisted_evidence_restores_notebook_sources(session):
    course, _book, _asset = _setup(session)
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
    live = sources_from_results(chunks, [])
    assert any(source.get("notebook_id") for source in live)


def test_notebook_citation_marker_maps_to_chunk(session):
    course, _book, _asset = _setup(session)
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
