from __future__ import annotations

import asyncio

import pytest

from app.ai import notebook_qa
from app.ai.deepseek import DeepSeekError
from app.ai.notebook_qa import NotebookAnswer, claims_for_answer
from app.api.v1.agent import send_agent_message
from app.api.v1.conversations import list_messages, send_message
from app.db.models import Conversation, ConversationMessage
from app.notes.document import normalize_document
from app.notes.store import write_document
from app.schemas.api import AgentMessageCreate
from app.schemas.conversations import ConversationMessageCreate
from tests.notebook_fixtures import make_asset, make_notebook, persist_ir

pytest_plugins = ["tests.notebook_fixtures"]


def test_notebook_answer_buffers_draft_and_uses_saved_revision(session, monkeypatch):
    book = make_notebook(session, None, "未分类笔记")
    body = normalize_document({
        "type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1, "blockId": "h-limit"},
             "content": [{"type": "text", "text": "极限"}]},
            {"type": "paragraph", "attrs": {"blockId": "p-limit"},
             "content": [{"type": "text", "text": "函数在一点附近的变化趋势称为极限。"}]},
        ],
    })
    write_document(session, book, body, expected_revision=0, origin="autosave")
    session.commit()

    class FakeClient:
        configured = True

        def __init__(self):
            self.calls = 0
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 10}

        def complete_json(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"answer_markdown": "DRAFT_SECRET 未核验初稿"}
            if self.calls == 2:
                return {"claims": [{"claim": "极限描述变化趋势", "verdict": "supported",
                                    "evidence_ids": ["N0"], "needs_web": False}]}
            if self.calls == 3:
                return {"uncovered_claims": []}
            if self.calls == 4:
                return {"answer_markdown": "最终答案：极限描述函数附近的变化趋势。"}
            if self.calls == 5:
                return {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                                    "review_claim_ids": ["claim-1"], "evidence_ids": ["N0"], "source_ids": []}]}
            return {"uncovered_claims": []}

    monkeypatch.setattr(notebook_qa, "DeepSeekClient", FakeClient)
    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="什么是极限？", history=[], allow_web=False,
    ))

    assert [event.get("status") for event in events if event["type"] == "status"] == [
        "reading_notebook", "drafting", "checking_sources", "checking_sources", "finalizing", "checking_sources",
    ]
    assert all(event["type"] != "delta" for event in events)
    result = events[-1]["result"]
    assert "DRAFT_SECRET" not in result.answer
    assert result.chunks[0].block_id == "h-limit"
    assert result.chunks[0].notebook_revision == book.document_revision
    assert result.process["verification"]["notebook_revision"] == book.document_revision


def test_notebook_answer_rejects_stale_revision_before_model_call(session, monkeypatch):
    book = make_notebook(session, None)
    monkeypatch.setattr(notebook_qa, "DeepSeekClient", lambda: (_ for _ in ()).throw(AssertionError("model called")))
    with pytest.raises(ValueError, match="已更新"):
        list(notebook_qa.run_notebook_answer(
            session, notebook_id=book.id, revision=book.document_revision + 1,
            question="问题", history=[], allow_web=False,
        ))


def test_document_ir_retrieval_never_crosses_notebook_ownership(session):
    notebook_a = make_notebook(session, None, "A")
    notebook_b = make_notebook(session, None, "B")
    asset_a = make_asset(session, notebook_a, "A.pdf")
    asset_b = make_asset(session, notebook_b, "B.pdf")
    run_a = persist_ir(session, notebook_a, asset_a)
    persist_ir(session, notebook_b, asset_b)

    chunks = notebook_qa._document_chunks(session, notebook_a, "极限的定义")

    assert chunks
    assert {chunk.notebook_id for chunk in chunks} == {notebook_a.id}
    assert {chunk.asset_id for chunk in chunks} == {asset_a.id}
    assert {chunk.parse_run_id for chunk in chunks} == {run_a.id}


def test_failed_web_verification_is_disclosed_in_final_answer(session, monkeypatch):
    book = make_notebook(session, None)
    write_document(session, book, normalize_document({
        "type": "doc", "content": [{"type": "paragraph", "attrs": {"blockId": "body-1"},
                                    "content": [{"type": "text", "text": "水在标准大气压下沸点为 100 摄氏度。"}]}],
    }), expected_revision=0, origin="autosave")
    session.commit()

    class FakeClient:
        configured = True
        last_usage = None

        def __init__(self):
            self.calls = 0

        def complete_json(self, _messages, **_kwargs):
            self.calls += 1
            return [
                {"answer_markdown": "初稿。"},
                {"claims": [{"claim": "沸点固定为 100 摄氏度", "verdict": "contradicted",
                             "evidence_ids": ["N0"], "needs_web": True}]},
                {"uncovered_claims": []},
                {"answer_markdown": "无法确定该结论。"},
                {"claims": [{"claim": "无法确定该结论", "verdict": "insufficient",
                             "review_claim_ids": ["claim-1"], "evidence_ids": [], "source_ids": []}]},
                {"uncovered_claims": []},
            ][self.calls - 1]

    monkeypatch.setattr(notebook_qa, "DeepSeekClient", FakeClient)
    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="水的沸点？", history=[], allow_web=False,
    ))
    result = events[-1]["result"]
    assert events[-1]["type"] == "verified_result"
    assert "未完成" in result.answer and "disabled_by_request" in result.answer
    assert result.process["verification"]["web_status"] == "disabled_by_request"


def test_web_evidence_is_reviewed_and_only_real_source_ids_are_kept(session, monkeypatch):
    book = make_notebook(session, None)
    write_document(session, book, normalize_document({
        "type": "doc", "content": [{"type": "paragraph", "attrs": {"blockId": "p-1"},
                                    "content": [{"type": "text", "text": "某结论有待确认。"}]}],
    }), expected_revision=0, origin="autosave")
    session.commit()

    class FakeClient:
        configured = True
        last_usage = None

        def __init__(self):
            self.calls = 0

        def complete_json(self, _messages, **_kwargs):
            self.calls += 1
            return [
                {"answer_markdown": "初稿。"},
                {"claims": [{"claim_id": "claim-1", "claim": "某结论", "verdict": "insufficient",
                             "evidence_ids": ["N0"], "needs_web": True}]},
                {"uncovered_claims": []},
                {"claims": [{"claim_id": "claim-1", "verdict": "supported",
                             "source_ids": ["W0", "W999"]}]},
                {"answer_markdown": "根据外部来源，结论得到支持。"},
                {"claims": [{"claim": "结论得到支持", "verdict": "supported",
                             "review_claim_ids": ["claim-1"], "evidence_ids": [], "source_ids": ["W0", "W999"]}]},
                {"uncovered_claims": []},
            ][self.calls - 1]

    monkeypatch.setattr(notebook_qa, "DeepSeekClient", FakeClient)
    monkeypatch.setattr(notebook_qa, "availability", lambda _policy: (True, "allowed"))
    monkeypatch.setattr(notebook_qa, "search_with_sources", lambda *_args, **_kwargs: [{
        "title": "权威来源", "site_name": "example.edu", "url": "https://example.edu/source",
        "snippet": "支持该结论", "published_at": None,
    }])
    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="为什么？", history=[], allow_web=True,
    ))
    result = events[-1]["result"]
    assert result.reviews[0]["external_verdict"] == "supported"
    assert result.reviews[0]["external_source_ids"] == ["W0"]
    assert claims_for_answer(result)[0]["web_indexes"] == [0]


def test_invalid_claim_review_fails_closed_without_final_answer(session, monkeypatch):
    book = make_notebook(session, None)
    write_document(session, book, normalize_document({
        "type": "doc", "content": [{"type": "paragraph", "attrs": {"blockId": "body"},
                                    "content": [{"type": "text", "text": "可用于回答的问题背景。"}]}],
    }), expected_revision=0, origin="autosave")
    session.commit()

    class FakeClient:
        configured = True
        last_usage = None

        def __init__(self):
            self.calls = 0

        def complete_json(self, _messages, **_kwargs):
            self.calls += 1
            return {"answer_markdown": "草稿"} if self.calls == 1 else {"claims": [None]}

    monkeypatch.setattr(notebook_qa, "DeepSeekClient", FakeClient)
    with pytest.raises(DeepSeekError, match="核验格式无效"):
        list(notebook_qa.run_notebook_answer(
            session, notebook_id=book.id, revision=book.document_revision,
            question="问题", history=[], allow_web=False,
        ))


def test_final_answer_with_unreviewed_claim_is_not_published(session, monkeypatch):
    book = make_notebook(session, None)
    write_document(session, book, normalize_document({
        "type": "doc", "content": [{"type": "paragraph", "attrs": {"blockId": "body"},
                                    "content": [{"type": "text", "text": "笔记中的背景。"}]}],
    }), expected_revision=0, origin="autosave")
    session.commit()

    class FakeClient:
        configured = True
        last_usage = None

        def __init__(self):
            self.calls = 0

        def complete_json(self, _messages, **_kwargs):
            self.calls += 1
            return [
                {"answer_markdown": "初稿含事实甲。"},
                {"claims": [{"claim": "事实甲", "verdict": "supported", "evidence_ids": ["N0"]}]},
                {"uncovered_claims": []},
                {"answer_markdown": "事实甲成立。事实乙也成立。"},
                {"claims": [{"claim": "事实甲成立", "verdict": "supported",
                             "review_claim_ids": ["claim-1"], "evidence_ids": ["N0"], "source_ids": []}]},
                {"uncovered_claims": ["事实乙也成立"]},
            ][self.calls - 1]

    monkeypatch.setattr(notebook_qa, "DeepSeekClient", FakeClient)
    with pytest.raises(DeepSeekError, match="最终答案存在未核验主张"):
        list(notebook_qa.run_notebook_answer(
            session, notebook_id=book.id, revision=book.document_revision,
            question="问题", history=[], allow_web=False,
        ))


def test_notebook_sse_sends_status_before_persisted_final_answer(session, monkeypatch):
    book = make_notebook(session, None)
    conversation = Conversation(
        course_id=None, notebook_id=book.id, title="新对话",
        scope="notebook", default_scope="notebook",
    )
    session.add(conversation)
    session.commit()

    def fake_pipeline(*_args, **_kwargs):
        yield {"type": "status", "status": "checking_sources"}
        yield {"type": "verified_result", "result": NotebookAnswer(
            answer="已核验的最终答案", chunks=[], web_results=[], reviews=[],
            model_version="notebook-verified:test", process={"verification": {"notebook_revision": 0}},
        )}

    monkeypatch.setattr("app.api.v1.agent.run_notebook_answer", fake_pipeline)
    response = send_agent_message(
        conversation.id,
        AgentMessageCreate(
            question="问题", scope="notebook",
            notebook_context={"notebook_id": book.id, "course_id": None, "revision": 0},
            idempotency_key="once",
        ),
        session,
    )

    async def collect():
        return "".join([chunk async for chunk in response.body_iterator])

    stream = asyncio.run(collect())
    assert '"type": "status"' in stream
    assert stream.index('"type": "status"') < stream.index('"type": "delta"')
    assert stream.index('"type": "delta"') < stream.index('"type": "final"')
    assert "已核验的最终答案" in stream
    assert "未经核验" not in stream
    saved = session.query(ConversationMessage).filter_by(
        conversation_id=conversation.id, role="assistant",
    ).one()
    assert "verification" in saved.process
    assert all("verification" not in (message.process or {}) for message in list_messages(conversation.id, session))


def test_json_conversation_endpoint_uses_same_verified_notebook_service(session, monkeypatch):
    book = make_notebook(session, None)
    conversation = Conversation(
        course_id=None, notebook_id=book.id, title="JSON 会话",
        scope="notebook", default_scope="notebook",
    )
    session.add(conversation)
    session.commit()
    monkeypatch.setattr("app.api.v1.conversations.run_notebook_answer", lambda *_a, **_kw: iter([
        {"type": "verified_result", "result": NotebookAnswer(
            answer="共享服务的已核验答案", chunks=[], web_results=[], reviews=[],
            model_version="notebook-verified:test", process={"thinking": "", "steps": [],
                "verification": {"notebook_revision": 0}},
        )},
    ]))

    message = send_message(
        conversation.id,
        ConversationMessageCreate(
            question="问题", scope="notebook",
            notebook_context={"notebook_id": book.id, "course_id": None, "revision": 0},
        ),
        session,
    )

    assert message.status == "completed"
    assert message.content == "共享服务的已核验答案"
    assert "verification" not in (message.process or {})
