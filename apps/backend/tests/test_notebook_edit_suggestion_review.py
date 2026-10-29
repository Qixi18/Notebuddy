"""Agent 正文修改的确认契约，以及 Notebook 删除/恢复的数据完整性。

架构约束（不可放宽）：
- 正文唯一真源是 ``Notebook.document_json``，版本由 ``document_revision`` 守护；
- Agent 只能产出 ``NotebookEditSuggestion``，必须经用户确认才写入；
- 未确认（提案、拒绝、失效、跨课程、已删除）时正文与 revision 必须一字不动。

本文件补的是交接文档点名的缺口：拒绝确认、批量合并（apply-all 此前没有任何
覆盖）、跨课程拒绝、失效建议、重复编号、已处理建议，以及删除/恢复。
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import HTTPException

from app.ai.agent_tools import execute_tool
from app.api.v1.notebook import (
    apply_course_edit_suggestions,
    delete_course_notebook,
    get_notebook_document,
    list_deleted_notebooks,
    put_notebook_document,
    restore_deleted_notebook,
    review_edit_suggestion,
)
from app.core.config import settings
from app.db.models import NotebookEditSuggestion
from app.notes.document import load_document, normalize_document
from app.notes.store import write_document
from app.schemas.notebook import (
    NotebookDocumentUpdate,
    NotebookEditSuggestionBatchReview,
    NotebookEditSuggestionReview,
    NotebookRestoreDeletedRequest,
)
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


@pytest.fixture
def checkpoint_ready(tmp_path, monkeypatch):
    """删除路径会先做一次数据库检查点（备份），需要一个真实存在的 SQLite 文件。

    session fixture 用内存库，与 ``settings.data_dir`` 下的文件库无关，所以这里
    造一个临时 data_dir，让真实删除流程（含 checkpoint）跑完整，而不是把
    ``_checkpoint`` 打桩绕过安全网。
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with sqlite3.connect(tmp_path / "notebook.sqlite3") as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS _checkpoint_probe (id INTEGER PRIMARY KEY)")
    return tmp_path


def _setup(session):
    """一门课、一本有正文的 Notebook（revision=1），可直接提案。"""
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
    return course, book


def _propose(session, course, book, content: str) -> str:
    outcome = execute_tool(
        session, course_id=course.id, name="propose_notebook_edits",
        arguments={"rationale": "补充", "edits": [{"op": "append", "content": content}]},
        scope="course", editable_notebook_id=book.id,
    )
    session.commit()
    assert outcome.suggestions, "提案没有生成修改建议"
    return outcome.suggestions[0]["id"]


def _body(session, book) -> tuple[str, int]:
    session.refresh(book)
    return book.document_json, book.document_revision


def test_rejecting_suggestion_leaves_body_and_revision_untouched(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "不该被写进正文的补充。")
    before_json, before_revision = _body(session, book)

    result = review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="reject", expected_revision=before_revision),
        session,
    )

    assert result["revision"] == before_revision
    assert "不该被写进正文的补充" not in json.dumps(result["content"], ensure_ascii=False)
    assert _body(session, book) == (before_json, before_revision)
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "rejected"


def test_accept_with_wrong_expected_revision_is_rejected_without_writing(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "版本不符时不应写入。")
    before_json, before_revision = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        review_edit_suggestion(
            book.id, suggestion_id,
            # base_revision 与当前一致，但调用方拿的 expected_revision 过期
            NotebookEditSuggestionReview(decision="accept", expected_revision=before_revision + 1),
            session,
        )

    assert captured.value.status_code == 409
    assert _body(session, book) == (before_json, before_revision)
    # 建议本身仍是 pending，用户可以刷新后重试，而不是被误标失效
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "pending"


def test_reviewing_same_suggestion_twice_is_refused(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "只能确认一次。")
    revision = book.document_revision
    review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="accept", expected_revision=revision),
        session,
    )

    with pytest.raises(HTTPException) as captured:
        review_edit_suggestion(
            book.id, suggestion_id,
            NotebookEditSuggestionReview(decision="accept", expected_revision=revision + 1),
            session,
        )
    assert captured.value.status_code == 409
    session.refresh(book)
    assert book.document_revision == revision + 1


def test_batch_apply_merges_multiple_suggestions_into_one_revision(session):
    course, book = _setup(session)
    first = _propose(session, course, book, "补充一：四则运算法则。")
    second = _propose(session, course, book, "补充二：夹逼定理的适用条件。")
    before_revision = book.document_revision

    result = apply_course_edit_suggestions(
        course.id, NotebookEditSuggestionBatchReview(suggestion_ids=[first, second]), session,
    )

    assert result["updated"] == 2
    assert len(result["notebooks"]) == 1
    # 同一本 Notebook 的两条建议只产生一次版本推进
    assert result["notebooks"][0]["revision"] == before_revision + 1
    content = json.dumps(
        load_document(_body(session, book)[0]).content, ensure_ascii=False,
    )
    assert "四则运算法则" in content
    assert "夹逼定理的适用条件" in content
    assert session.get(NotebookEditSuggestion, first).status == "accepted"
    assert session.get(NotebookEditSuggestion, second).status == "accepted"


def test_batch_apply_refuses_duplicate_ids(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "重复编号。")
    before = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        apply_course_edit_suggestions(
            course.id,
            NotebookEditSuggestionBatchReview(suggestion_ids=[suggestion_id, suggestion_id]),
            session,
        )

    assert captured.value.status_code == 422
    assert _body(session, book) == before


def test_batch_apply_refuses_foreign_course_suggestion(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "跨课程不应被合并。")
    other_course = make_course(session, "另一门课")
    before = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        apply_course_edit_suggestions(
            other_course.id,
            NotebookEditSuggestionBatchReview(suggestion_ids=[suggestion_id]),
            session,
        )

    assert captured.value.status_code == 404
    assert _body(session, book) == before
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "pending"


def test_batch_apply_marks_stale_when_user_edited_after_proposal(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "基于旧版本的建议。")
    base_revision = book.document_revision

    # 用户在提案之后自己改了正文
    updated = load_document(book.document_json).content
    updated["content"].append({
        "type": "paragraph", "attrs": {"blockId": "user-2"},
        "content": [{"type": "text", "text": "用户自己写的内容"}],
    })
    write_document(session, book, updated, expected_revision=base_revision, origin="autosave")
    session.commit()
    after_user_edit = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        apply_course_edit_suggestions(
            course.id, NotebookEditSuggestionBatchReview(suggestion_ids=[suggestion_id]), session,
        )

    assert captured.value.status_code == 409
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "stale"
    # 用户正文必须原样保留
    assert _body(session, book) == after_user_edit
    assert "基于旧版本的建议" not in after_user_edit[0]


def test_batch_apply_refuses_already_reviewed_suggestion(session):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "已拒绝的建议。")
    review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="reject", expected_revision=book.document_revision),
        session,
    )
    before = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        apply_course_edit_suggestions(
            course.id, NotebookEditSuggestionBatchReview(suggestion_ids=[suggestion_id]), session,
        )

    assert captured.value.status_code == 409
    assert _body(session, book) == before


def test_batch_apply_ignores_suggestions_of_deleted_notebook(session, checkpoint_ready):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "笔记已删除。")
    delete_course_notebook(course.id, book.id, session)
    session.commit()
    before = _body(session, book)

    with pytest.raises(HTTPException) as captured:
        apply_course_edit_suggestions(
            course.id, NotebookEditSuggestionBatchReview(suggestion_ids=[suggestion_id]), session,
        )

    assert captured.value.status_code == 404
    assert _body(session, book) == before
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "pending"


def test_deleted_notebook_keeps_body_and_restores_into_course(session, checkpoint_ready):
    course, book = _setup(session)
    document_json, revision = _body(session, book)

    delete_course_notebook(course.id, book.id, session)
    session.commit()

    # 软删除：行还在，正文与版本不动，只是不可见
    assert _body(session, book) == (document_json, revision)
    assert book.deleted_at is not None
    assert [row["id"] for row in list_deleted_notebooks(session)] == [book.id]

    # 删除后不能按课程读取或写入
    with pytest.raises(HTTPException) as read_error:
        get_notebook_document(course.id, book.id, session)
    assert read_error.value.status_code == 404
    with pytest.raises(HTTPException) as write_error:
        put_notebook_document(
            course.id, book.id,
            NotebookDocumentUpdate(
                content=load_document(document_json).content, expected_revision=revision,
            ),
            session,
        )
    assert write_error.value.status_code == 404

    restored = restore_deleted_notebook(
        book.id, NotebookRestoreDeletedRequest(course_id=course.id), session,
    )
    assert restored["id"] == book.id
    session.refresh(book)
    assert book.deleted_at is None
    assert book.course_id == course.id
    # 恢复后正文与版本必须还是原样，不能因为删除/恢复而重写
    assert _body(session, book) == (document_json, revision)


def test_restored_notebook_can_still_reject_its_pending_suggestion(session, checkpoint_ready):
    course, book = _setup(session)
    suggestion_id = _propose(session, course, book, "删除再恢复后仍然可选。")
    delete_course_notebook(course.id, book.id, session)
    session.commit()
    restore_deleted_notebook(book.id, NotebookRestoreDeletedRequest(course_id=course.id), session)
    session.commit()
    before_json, before_revision = _body(session, book)

    result = review_edit_suggestion(
        book.id, suggestion_id,
        NotebookEditSuggestionReview(decision="reject", expected_revision=before_revision),
        session,
    )

    assert result["revision"] == before_revision
    assert _body(session, book) == (before_json, before_revision)
    assert session.get(NotebookEditSuggestion, suggestion_id).status == "rejected"
