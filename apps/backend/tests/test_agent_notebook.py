"""Notebook-scoped read tools and legacy suggestion compatibility."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.ai.agent_tools import build_tool_specs, execute_tool
from app.api.v1.agent import send_agent_message
from app.api.v1.conversations import create_conversation
from app.api.v1.notebook import list_edit_suggestions, review_edit_suggestion
from app.db.models import Conversation, ConversationMessage, NotebookEditSuggestion
from app.notes.document import dump_document, load_document, normalize_document
from app.notes.edits import apply_edits
from app.notes.store import write_document
from app.schemas.api import AgentMessageCreate, ConversationCreate
from app.schemas.notebook import NotebookEditSuggestionReview
from app.services.conversations import resolve_legacy_note_target
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


def _setup(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    persist_ir(session, book, asset)
    body = normalize_document({
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 1, "blockId": "h-1"},
             "content": [{"type": "text", "text": "第一章 极限"}]},
            {"type": "paragraph", "attrs": {"blockId": "p-1"},
             "content": [{"type": "text", "text": "极限描述函数在一点附近的变化趋势。"}]},
        ],
    })
    write_document(session, book, body, expected_revision=0, origin="autosave")
    session.commit()
    return course, book, asset


def _seed_existing_suggestion(session, book, edits, rationale="测试遗留建议"):
    """为兼容 API 测试种入既有数据；Agent 不再具备创建建议的工具。"""
    proposed = apply_edits(load_document(book.document_json).content, edits)
    suggestion = NotebookEditSuggestion(
        notebook_id=book.id,
        base_revision=book.document_revision,
        rationale=rationale,
        ops_json=json.dumps(edits, ensure_ascii=False),
        proposed_document_json=dump_document(proposed),
        status="pending",
    )
    session.add(suggestion)
    session.flush()
    return suggestion


def test_tool_specs_use_notebook_names():
    specs = build_tool_specs(scope="global", editable_notebook=True, allow_web=False)
    names = {spec["function"]["name"] for spec in specs}
    assert {"search_course", "read_notebook", "list_course_notebooks",
            "search_forest", "get_source_coverage"}.issubset(names)
    assert "propose_notebook_edits" not in names
    assert "read_note" not in names
    assert "propose_note_edits" not in names


def test_notebook_scope_has_only_locked_notebook_read_tool():
    specs = build_tool_specs(scope="notebook", editable_notebook=True, allow_web=True, allow_quiz=True)
    assert {spec["function"]["name"] for spec in specs} == {"read_notebook"}


def test_legacy_note_resolution_rejects_cross_table_id_collision():
    notebook_a = SimpleNamespace(id="shared-id", course_id="course-1", deleted_at=None)
    notebook_b = SimpleNamespace(id="book-b", course_id="course-1", deleted_at=None)
    legacy_note = SimpleNamespace(id="shared-id", notebook_id="book-b")

    class Lookup:
        def get(self, model, identifier):
            if model.__name__ == "Notebook":
                return {"shared-id": notebook_a, "book-b": notebook_b}.get(identifier)
            if model.__name__ == "Note" and identifier == "shared-id":
                return legacy_note
            return None

    resolved, error = resolve_legacy_note_target(Lookup(), "shared-id", "course-1")
    assert resolved is None
    assert error is not None and "同时指向" in error


def test_search_course_and_read_notebook(session):
    course, book, _asset = _setup(session)
    outcome = execute_tool(session, course_id=course.id, name="search_course",
                           arguments={"query": "极限 变化趋势"}, scope="course")
    assert outcome.chunks
    assert any(chunk.kind == "notebook" for chunk in outcome.chunks)
    read = execute_tool(session, course_id=course.id, name="read_notebook",
                        arguments={"notebook_id": book.id}, scope="course")
    assert "第一章 极限" in read.payload_text
    assert "变化趋势" in read.payload_text


def test_read_notebook_rejects_foreign_course(session):
    _course, _book, _asset = _setup(session)
    other = make_course(session, "别的课")
    foreign = make_notebook(session, other)
    outcome = execute_tool(session, course_id=_course.id, name="read_notebook",
                           arguments={"notebook_id": foreign.id}, scope="course")
    assert "不属于当前课程" in outcome.payload_text or "拒绝" in outcome.payload_text


def test_locked_agent_conversation_rejects_scope_widening(session):
    course, book, _asset = _setup(session)
    conversation = Conversation(
        course_id=course.id, title="锁定笔记", default_scope="note",
        scope="note", note_id=book.id, note_title=book.title,
    )
    session.add(conversation)
    session.flush()
    session.add(ConversationMessage(
        conversation_id=conversation.id, role="user", content="已在锁定笔记范围提问",
        status="completed",
    ))
    session.commit()

    from app.services.errors import ApplicationError

    with pytest.raises(ApplicationError) as captured:
        send_agent_message(
            conversation.id, AgentMessageCreate(question="扩大范围", scope="course"), session,
        )
    assert captured.value.status_code == 409
    assert len(conversation.messages) == 1


def test_note_conversation_creation_checks_notebook_course(session):
    course, _book, _asset = _setup(session)
    other_course = make_course(session, "另一个课程")
    foreign_book = make_notebook(session, other_course)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
        create_conversation(
            course.id,
            ConversationCreate(scope="note", default_scope="note", note_id=foreign_book.id),
            session,
        )
    assert captured.value.status_code == 404


def test_agent_rejects_notebook_context_from_foreign_course(session):
    course, _book, _asset = _setup(session)
    foreign_course = make_course(session, "隔离课程")
    foreign_book = make_notebook(session, foreign_course)
    conversation = create_conversation(
        course.id,
        ConversationCreate(scope="course", default_scope="course"),
        session,
    )

    from app.services.errors import ApplicationError

    with pytest.raises(ApplicationError) as captured:
        send_agent_message(
            conversation.id,
            AgentMessageCreate(
                question="跨课程读取", scope="course",
                notebook_context={
                    "course_id": foreign_course.id, "notebook_id": foreign_book.id,
                    "revision": foreign_book.document_revision,
                },
            ),
            session,
        )
    assert captured.value.status_code == 404


def test_agent_cannot_create_notebook_edit_suggestions(session):
    course, book, _asset = _setup(session)
    before = book.document_json
    outcome = execute_tool(
        session, course_id=course.id, name="propose_notebook_edits",
        arguments={
            "rationale": "补充易错点",
            "edits": [{"op": "insert_after_heading", "anchor": "第一章 极限",
                       "content": "易错点：左右极限不相等时极限不存在。"}],
        },
        scope="course", editable_notebook_id=book.id,
    )
    session.commit()
    assert "工具" in outcome.payload_text
    assert "建议" not in outcome.suggestions
    session.refresh(book)
    assert book.document_json == before
    assert session.query(NotebookEditSuggestion).filter_by(notebook_id=book.id).count() == 0


def test_accepting_suggestion_writes_document(session):
    _course, book, _asset = _setup(session)
    suggestion = _seed_existing_suggestion(session, book, [
        {"op": "append", "content": "补充：极限的四则运算法则。"},
    ])
    suggestion_id = suggestion.id
    revision = book.document_revision
    result = review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="accept", expected_revision=revision),
        session,
    )
    session.commit()
    assert result["revision"] == revision + 1
    assert "四则运算法则" in json.dumps(result["content"], ensure_ascii=False)
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "accepted"


def test_partial_acceptance_replays_only_selected_structured_operations(session):
    _course, book, _asset = _setup(session)
    suggestion = _seed_existing_suggestion(session, book, [
        {"op": "append", "content": "补充：极限的四则运算法则。"},
        {"op": "insert_after_heading", "anchor": "第一章 极限",
         "content": "易错点：左右极限不相等时极限不存在。"},
    ], rationale="补充两点")
    suggestion_id = suggestion.id
    listed = list_edit_suggestions(book.id, "pending", session)
    assert listed[0]["operations"][1]["op"] == "insert_after_heading"
    assert listed[0]["proposed_content"]

    revision = book.document_revision
    result = review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="accept", expected_revision=revision,
                                     selected_operation_indices=[1]),
        session,
    )
    assert "左右极限不相等" in json.dumps(result["content"], ensure_ascii=False)
    assert "四则运算法则" not in json.dumps(result["content"], ensure_ascii=False)
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "partially_accepted"


def test_stale_suggestion_is_rejected_after_user_edit(session):
    _course, book, _asset = _setup(session)
    suggestion = _seed_existing_suggestion(session, book, [
        {"op": "append", "content": "补充内容。"},
    ])
    suggestion_id = suggestion.id
    base_revision = book.document_revision
    # User edits after the suggestion was created.
    updated = normalize_document(load_document(book.document_json).content)
    updated["content"].append({
        "type": "paragraph", "attrs": {"blockId": "user-2"},
        "content": [{"type": "text", "text": "用户新内容"}],
    })
    write_document(session, book, updated, expected_revision=base_revision, origin="autosave")
    session.commit()

    from app.services.errors import ApplicationError

    with pytest.raises(ApplicationError) as captured:
        review_edit_suggestion(
            book.id, suggestion_id,
            NotebookEditSuggestionReview(decision="accept",
                                          expected_revision=book.document_revision),
            session,
        )
    assert captured.value.status_code == 409
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "stale"


def test_search_forest_finds_notebook_body(session):
    course, _book, _asset = _setup(session)
    outcome = execute_tool(session, course_id=course.id, name="search_forest",
                           arguments={"query": "变化趋势"}, scope="global")
    assert "第一章 极限" in outcome.payload_text
