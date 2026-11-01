"""P0-QA-02：course / global / 历史 note 的答疑也必须「核验后发布」。

覆盖范围：
- 证据编号映射（N/D/W）与"未知编号不认"；
- 证据不足时降级为 insufficient 并给出公开 notice，而不是悄悄放行；
- 门禁结构无效时 fail closed（抛错，调用方不得发布正文）；
- 没有证据时直接标记未核验，且不调用模型；
- SSE 入口：核验失败时流里不出现正文 delta，只出现错误事件。
"""

from __future__ import annotations

import json

import pytest

from app.ai import verified_answer
from app.ai.deepseek import DeepSeekError
from app.ai.verified_answer import AnswerVerificationError, verify_answer
from app.retrieval.service import RetrievedChunk

pytest_plugins = ["tests.notebook_fixtures"]


def _chunk(text: str, *, kind: str = "notebook", **kwargs) -> RetrievedChunk:
    return RetrievedChunk(
        material_id=None if kind == "notebook" else kwargs.pop("material_id", None),
        lecture_title=kwargs.pop("title", "笔记" if kind == "notebook" else "资料.pdf"),
        page_number=kwargs.pop("page_number", 0), text=text, score=1.0, kind=kind,
        notebook_id=kwargs.pop("notebook_id", "book-1"),
        block_id=kwargs.pop("block_id", "p-1" if kind == "notebook" else None),
        **kwargs,
    )


class FakeClient:
    configured = True
    last_usage = None

    def __init__(self, payload: dict | None = None, *, error: bool = False) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[list[dict]] = []

    def complete_json(self, messages, **_kwargs):
        self.calls.append(messages)
        if self.error:
            raise DeepSeekError("provider down")
        return self.payload


def test_supported_claim_maps_to_chunk_and_web_indexes(session):
    notebook = _chunk("极限描述函数附近的变化趋势。")
    document = _chunk("教材原文：极限的定义。", kind="document", material_id="m-1",
                      page_number=3, parse_run_id="run-1", document_block_id="b-1")
    web = [{"title": "百科", "url": "https://example.com/a", "site_name": "example.com",
            "snippet": "极限的定义"}]
    client = FakeClient({"claims": [
        {"claim": "极限描述变化趋势", "verdict": "supported",
         "evidence_ids": ["N0", "D0"], "source_ids": ["W0", "W9"]},
    ]})

    verified = verify_answer(
        session, answer="极限描述函数附近的变化趋势。", chunks=[document, notebook],
        web_results=web, course_id=None, scope="course", client=client,
    )

    assert verified.mode == verified_answer.MODE_VERIFIED
    assert verified.verification["notice"] is None
    # Notebook 片段永远排在前，DocumentIR 在后
    assert [chunk.kind for chunk in verified.chunks] == ["notebook", "document"]
    claims = verified.claims
    assert claims[0]["chunk_indexes"] == [0, 1]
    assert claims[0]["web_indexes"] == [0]  # W9 不是真实来源，被丢弃


def test_unsupported_claim_gets_notice_and_is_not_published_as_supported(session):
    client = FakeClient({"claims": [
        {"claim": "某数值结论", "verdict": "insufficient", "evidence_ids": []},
        {"claim": "某定义", "verdict": "supported", "evidence_ids": ["N0"]},
    ]})
    verified = verify_answer(
        session, answer="某数值结论加某定义。", chunks=[_chunk("某定义")],
        web_results=[], course_id=None, scope="course", client=client,
    )

    assert verified.mode == verified_answer.MODE_PARTIAL
    assert verified.verification["notice"] == verified_answer.PARTIAL_NOTICE
    assert verified.verification["claims"][0]["verdict"] == "insufficient"
    assert verified.verification["claims"][1]["verdict"] == "supported"
    # notice 不进正文，避免污染答案
    assert verified.answer == "某数值结论加某定义。"
    assert verified.claims[0]["chunk_indexes"] == []


def test_supported_verdict_without_valid_evidence_is_downgraded(session):
    client = FakeClient({"claims": [
        {"claim": "凭空来源", "verdict": "supported", "evidence_ids": ["N7", "X1"]},
    ]})
    verified = verify_answer(
        session, answer="凭空来源的结论。", chunks=[_chunk("正文")], web_results=[],
        course_id=None, scope="course", client=client,
    )
    assert verified.mode == verified_answer.MODE_PARTIAL
    assert verified.verification["claims"][0]["verdict"] == "insufficient"
    assert verified.verification["claims"][0]["evidence_ids"] == []


def test_malformed_provider_output_fails_closed(session):
    client = FakeClient({"claims": "not-a-list"})
    with pytest.raises(AnswerVerificationError, match="结构无效"):
        verify_answer(session, answer="答案", chunks=[_chunk("正文")], web_results=[],
                      course_id=None, scope="course", client=client)


def test_claim_with_unknown_verdict_fails_closed(session):
    client = FakeClient({"claims": [{"claim": "某主张", "verdict": "probably"}]})
    with pytest.raises(AnswerVerificationError, match="格式无效"):
        verify_answer(session, answer="答案", chunks=[_chunk("正文")], web_results=[],
                      course_id=None, scope="course", client=client)


def test_no_evidence_returns_unverified_mode_without_model_call(session):
    client = FakeClient({"claims": []})
    verified = verify_answer(session, answer="你好，我是老师。", chunks=[], web_results=[],
                             course_id=None, scope="global", client=client)
    assert verified.mode == verified_answer.MODE_NO_EVIDENCE
    assert verified.verification["notice"] == verified_answer.UNVERIFIED_NOTICE
    assert client.calls == []
    assert verified.answer == "你好，我是老师。"


def test_unconfigured_provider_marks_verification_unavailable(session):
    class Unconfigured:
        configured = False
        last_usage = None

    verified = verify_answer(session, answer="本地检索摘录", chunks=[_chunk("正文")],
                             web_results=[], course_id=None, scope="course",
                             client=Unconfigured())
    assert verified.mode == verified_answer.MODE_UNAVAILABLE
    assert verified.verification["notice"] == verified_answer.UNAVAILABLE_NOTICE


def test_agent_stream_does_not_publish_body_when_gate_fails(session, monkeypatch):
    """SSE 入口：门禁异常时流里不能出现正文，只能出现错误事件。"""

    from app.api.v1 import agent as agent_api

    def fake_run_agent(*_args, **_kwargs):
        yield {"type": "delta", "text": "DRAFT_SECRET 未核验正文"}
        yield {"type": "final", "answer": "DRAFT_SECRET 未核验正文", "chunks": [],
               "web_results": [], "suggestions": []}

    def failing_gate(*_args, **_kwargs):
        raise AnswerVerificationError("核验结构无效")

    monkeypatch.setattr(agent_api, "run_agent", fake_run_agent)
    monkeypatch.setattr(agent_api, "verify_answer", failing_gate)

    from app.db.models import Conversation, Course
    from app.schemas.api import AgentMessageCreate

    course = Course(name="课程")
    session.add(course)
    session.flush()
    conversation = Conversation(course_id=course.id, title="会话",
                                default_scope="course", scope="course")
    session.add(conversation)
    session.commit()

    import asyncio

    response = agent_api.send_agent_message(
        conversation.id, AgentMessageCreate(question="问题"), session,
    )

    async def collect():
        return "".join([chunk async for chunk in response.body_iterator])

    stream = asyncio.run(collect())
    assert "DRAFT_SECRET" not in stream
    assert '"type": "error"' in stream
    assert '"type": "delta"' not in stream
    payload = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
    assert payload[-1]["type"] == "error"


def test_global_scope_uses_same_gate_as_course(session):
    client = FakeClient({"claims": [
        {"claim": "跨课程结论", "verdict": "supported", "evidence_ids": ["N0"]},
    ]})
    verified = verify_answer(
        session, answer="跨课程结论成立。", chunks=[_chunk("跨课程正文")], web_results=[],
        course_id="course-1", scope="global", client=client,
    )
    assert verified.mode == verified_answer.MODE_VERIFIED
    assert verified.claims[0]["chunk_indexes"] == [0]
