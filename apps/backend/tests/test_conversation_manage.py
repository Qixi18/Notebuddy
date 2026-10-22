"""Conversation rename (PATCH) and delete (DELETE) endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.v1 import conversations
from app.db.database import Base, get_db
from app.db.models import Conversation, ConversationMessage, Course, MessageEvidence
from app.main import app


def _setup(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'manage.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with factory() as db:
        course = Course(name="测试课程")
        db.add(course)
        db.flush()
        conversation = Conversation(course_id=course.id, title="新对话")
        db.add(conversation)
        db.commit()
        ids = (course.id, conversation.id)
    return TestClient(app), factory, ids


def test_rename_updates_title_and_rejects_empty(tmp_path) -> None:
    client, _factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        renamed = client.patch(f"/api/v1/conversations/{conversation_id}", json={"title": "红黑树专题"}).json()
        assert renamed["title"] == "红黑树专题"
        listed = client.get(f"/api/v1/courses/{course_id}/conversations").json()
        assert listed[0]["title"] == "红黑树专题"
        # 空标题 / 缺失字段 → 422
        assert client.patch(f"/api/v1/conversations/{conversation_id}", json={"title": "   "}).status_code == 422
        assert client.patch(f"/api/v1/conversations/{conversation_id}", json={}).status_code == 422
        assert client.patch("/api/v1/conversations/missing", json={"title": "x"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_delete_removes_conversation_and_cascades_messages_and_evidence(tmp_path, monkeypatch) -> None:
    client, factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        result = {
            "answer": "有来源的回答", "chunks": [], "web_results": [
                {"title": "资料", "url": "https://example.org/s", "site_name": "e", "snippet": "s"},
            ],
            "claims": [{"claim_key": "answer", "chunk_indexes": [], "web_indexes": [0]}],
            "model_version": "test-model",
        }
        monkeypatch.setattr(conversations, "run_answer", lambda *_a, **_k: result)
        # 先造一条消息（带证据），验证删除时级联清掉
        posted = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"question": "第一问"})
        assert posted.status_code == 201
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ConversationMessage)) == 2  # user + assistant
            assert db.scalar(select(func.count()).select_from(MessageEvidence)) >= 1

        deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
        assert deleted.status_code == 204
        # 列表与消息都不见了
        assert client.get(f"/api/v1/courses/{course_id}/conversations").json() == []
        assert client.get(f"/api/v1/conversations/{conversation_id}/messages").status_code == 404
        # 消息与证据被级联清空，无孤儿行
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ConversationMessage)) == 0
            assert db.scalar(select(func.count()).select_from(MessageEvidence)) == 0
            assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        # 重复删除 → 404
        assert client.delete(f"/api/v1/conversations/{conversation_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
