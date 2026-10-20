"""Both conversation transports keep the same evidence and history contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent, conversations
from app.db.database import Base, get_db
from app.db.models import (
    Conversation,
    Course,
    Material,
    MaterialPage,
    PageBlock,
    SourceRef,
    WebSource,
)
from app.main import app
from app.retrieval.service import RetrievedChunk
from app.services.conversations import persist_assistant_message


def test_both_transports_persist_web_evidence_and_replay_sources(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'conversation.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        with factory() as db:
            course = Course(name="测试课程")
            db.add(course)
            db.flush()
            conversation = Conversation(course_id=course.id, title="答疑")
            db.add(conversation)
            db.add(WebSource(
                course_id=course.id, search_query="测试", title="资料", url="https://example.org/source",
                site_name="example.org", snippet="可核查的网络内容",
            ))
            db.commit()
            course_id, conversation_id = course.id, conversation.id

        result = {
            "answer": "有来源的回答", "chunks": [],
            "web_results": [{"title": "资料", "url": "https://example.org/source",
                             "site_name": "example.org", "snippet": "可核查的网络内容"}],
            "claims": [{"claim_key": "answer", "web_indexes": [0]}],
            "model_version": "test-model",
        }
        monkeypatch.setattr(conversations, "run_answer", lambda *_a, **_k: result)

        def run_agent(*_a, **_k):
            yield {"type": "final", **result, "mode": "agent", "suggestions": []}

        monkeypatch.setattr(agent, "run_agent", run_agent)
        client = TestClient(app)
        plain = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"question": "第一问"})
        streamed = client.post(f"/api/v1/conversations/{conversation_id}/agent-messages", json={"question": "第二问"})
        replay = client.get(f"/api/v1/conversations/{conversation_id}/messages")

        assert plain.status_code == 201, plain.text
        assert plain.json()["evidence"][0]["evidence_type"] == "web_supplement"
        assert plain.json()["sources"][0]["url"] == "https://example.org/source"
        assert streamed.status_code == 200, streamed.text
        assert '"type": "final"' in streamed.text
        assert '"source_type": "web"' in streamed.text
        assert "https://example.org/source" in streamed.text
        assert replay.status_code == 200, replay.text
        assistants = [item for item in replay.json() if item["role"] == "assistant"]
        users = [item for item in replay.json() if item["role"] == "user"]
        assert [item["content"] for item in users] == ["第一问", "第二问"]
        assert len(assistants) == 2
        assert all(item["evidence"][0]["evidence_type"] == "web_supplement" for item in assistants)
        assert all(item["sources"][0]["url"] == "https://example.org/source" for item in assistants)

        assert client.get("/api/v1/conversations/missing/messages").json()["detail"] == "会话不存在"
        with factory() as db:
            db.get(Course, course_id).deleted_at = datetime.now(UTC)
            db.commit()
        hidden = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        assert hidden.status_code == 404
        assert hidden.json()["detail"] == "课程不存在"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_failed_answers_remain_in_history_for_both_transports(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'failed.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        with factory() as db:
            course = Course(name="测试课程")
            db.add(course)
            db.flush()
            conversation = Conversation(course_id=course.id, title="失败回归")
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        def fail(*_args, **_kwargs):
            raise RuntimeError("model failed")

        def fail_agent(*_args, **_kwargs):
            raise RuntimeError("agent failed")
            yield  # Keep this a generator, matching the streaming interface.

        monkeypatch.setattr(conversations, "run_answer", fail)
        monkeypatch.setattr(agent, "run_agent", fail_agent)
        monkeypatch.setattr(agent, "run_answer", fail)
        client = TestClient(app)
        plain = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"question": "第一问"})
        streamed = client.post(f"/api/v1/conversations/{conversation_id}/agent-messages", json={"question": "第二问"})
        replay = client.get(f"/api/v1/conversations/{conversation_id}/messages")

        assert plain.status_code == 201
        assert plain.json()["status"] == "failed"
        assert streamed.status_code == 200
        assert '"type": "error"' in streamed.text
        assert replay.status_code == 200
        assistants = [item for item in replay.json() if item["role"] == "assistant"]
        assert len(assistants) == 2
        assert all(item["status"] == "failed" and item["mode"] == "failed" for item in assistants)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_missing_course_reference_is_not_saved_as_supported_evidence(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'missing-source.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as db:
            course = Course(name="测试课程")
            db.add(course)
            db.flush()
            conversation = Conversation(course_id=course.id, title="来源校验")
            db.add(conversation)
            db.flush()
            chunk = RetrievedChunk(
                material_id="missing-material", lecture_title="讲次", page_number=1,
                text="未绑定来源的片段", score=1.0, source_ref_id="missing-ref",
                direct_support=True,
            )
            assistant = persist_assistant_message(
                db, conversation=conversation, learning_goal=None,
                content="回答", model_version="test", chunks=[chunk], web_results=[],
                claims=[{"claim_key": "answer", "chunk_indexes": [0], "evidence_type": "course_direct"}],
            )
            evidence = assistant.evidence[0]
            assert evidence.source_ref_id is None
            assert evidence.evidence_type == "general_explanation"
            assert evidence.support_level == "unverified"
    finally:
        engine.dispose()


def test_course_evidence_requires_active_reference_in_conversation_course(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'course-source.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as db:
            own, foreign = Course(name="本课程"), Course(name="其他课程")
            db.add_all([own, foreign])
            db.flush()
            conversation = Conversation(course_id=own.id, title="来源校验")
            db.add(conversation)
            db.flush()
            refs = []
            for course in (own, foreign):
                material = Material(
                    course_id=course.id, lecture_title="第一讲", original_filename="test.pdf",
                    stored_filename=f"{course.id}.pdf", size_bytes=1,
                )
                db.add(material)
                db.flush()
                page = MaterialPage(material_id=material.id, page_number=1, raw_text="定义")
                db.add(page)
                db.flush()
                block = PageBlock(page_id=page.id, block_type="text", content="定义", position=0)
                db.add(block)
                db.flush()
                ref = SourceRef(page_block_id=block.id, quote="定义")
                db.add(ref)
                db.flush()
                refs.append((material.id, block.id, ref.id))

            chunks = [
                RetrievedChunk(material_id=material_id, lecture_title="第一讲", page_number=1,
                text="定义", score=1.0, page_block_id=block_id, source_ref_id=ref_id)
                for material_id, block_id, ref_id in refs
            ]
            assistant = persist_assistant_message(
                db, conversation=conversation, learning_goal=None, content="回答", model_version="test",
                chunks=chunks, web_results=[], claims=[
                    {"claim_key": "own", "chunk_indexes": [0]},
                    {"claim_key": "foreign", "chunk_indexes": [1]},
                ],
            )
            evidence = {item.claim_key: item for item in assistant.evidence}
            assert evidence["own"].source_ref_id == refs[0][2]
            assert evidence["own"].evidence_type == "course_direct"
            assert evidence["foreign"].source_ref_id is None
            assert evidence["foreign"].evidence_type == "general_explanation"
    finally:
        engine.dispose()
