"""Agent tools and Notebook edit suggestions (no legacy Note bodies)."""

from __future__ import annotations

import json

import pytest

from app.ai.agent_tools import build_tool_specs, execute_tool
from app.api.v1.notebook import list_edit_suggestions, review_edit_suggestion
from app.db.models import NotebookEditSuggestion
from app.notes.document import load_document, normalize_document
from app.notes.store import write_document
from app.schemas.notebook import NotebookEditSuggestionReview
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


def test_tool_specs_use_notebook_names():
    specs = build_tool_specs(scope="global", editable_notebook=True, allow_web=False)
    names = {spec["function"]["name"] for spec in specs}
    assert {"search_course", "read_notebook", "list_course_notebooks",
            "search_forest", "get_source_coverage", "propose_notebook_edits"}.issubset(names)
    assert "read_note" not in names
    assert "propose_note_edits" not in names


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


def test_propose_notebook_edits_is_pending_and_body_unchanged(session):
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
    assert outcome.suggestions and outcome.suggestions[0]["type"] == "notebook_edit_suggestion"
    session.refresh(book)
    assert book.document_json == before
    suggestion = session.get(NotebookEditSuggestion, outcome.suggestions[0]["id"])
    assert suggestion.status == "pending"
    proposed = load_document(suggestion.proposed_document_json).content
    assert "左右极限不相等" in json.dumps(proposed, ensure_ascii=False)


def test_accepting_suggestion_writes_document(session):
    course, book, _asset = _setup(session)
    outcome = execute_tool(
        session, course_id=course.id, name="propose_notebook_edits",
        arguments={"rationale": "补充", "edits": [
            {"op": "append", "content": "补充：极限的四则运算法则。"}]},
        scope="course", editable_notebook_id=book.id,
    )
    session.commit()
    suggestion_id = outcome.suggestions[0]["id"]
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
    course, book, _asset = _setup(session)
    outcome = execute_tool(
        session, course_id=course.id, name="propose_notebook_edits",
        arguments={"rationale": "补充两点", "edits": [
            {"op": "append", "content": "补充：极限的四则运算法则。"},
            {"op": "insert_after_heading", "anchor": "第一章 极限",
             "content": "易错点：左右极限不相等时极限不存在。"},
        ]}, scope="course", editable_notebook_id=book.id,
    )
    session.commit()
    suggestion_id = outcome.suggestions[0]["id"]
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
    course, book, _asset = _setup(session)
    outcome = execute_tool(
        session, course_id=course.id, name="propose_notebook_edits",
        arguments={"rationale": "补充", "edits": [
            {"op": "append", "content": "补充内容。"}]},
        scope="course", editable_notebook_id=book.id,
    )
    session.commit()
    suggestion_id = outcome.suggestions[0]["id"]
    base_revision = book.document_revision
    # User edits after the suggestion was created.
    updated = normalize_document(load_document(book.document_json).content)
    updated["content"].append({
        "type": "paragraph", "attrs": {"blockId": "user-2"},
        "content": [{"type": "text", "text": "用户新内容"}],
    })
    write_document(session, book, updated, expected_revision=base_revision, origin="autosave")
    session.commit()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
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
