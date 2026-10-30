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


def test_search_course_messages_returns_hits_with_snippet(tmp_path) -> None:
    """P6 消息全文搜索：提问与回答都命中；跨课程不串；空 q 返回空。"""
    client, factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        with factory() as db:
            other_course = Course(name="别的课程")
            db.add(other_course)
            db.flush()
            other_conversation = Conversation(course_id=other_course.id, title="别课会话")
            db.add(other_conversation)
            db.commit()
            other_conversation_id = other_conversation.id

        def post(conv_id: str, question: str) -> None:
            assert client.post(f"/api/v1/conversations/{conv_id}/messages", json={"question": question}).status_code == 201

        post(conversation_id, "什么是红黑树的旋转规则？")
        post(other_conversation_id, "红黑树在另一门课的提问")
        # 空关键词 → 空结果
        assert client.get(f"/api/v1/courses/{course_id}/conversations/search", params={"q": ""}).json() == []

        hits = client.get(f"/api/v1/courses/{course_id}/conversations/search", params={"q": "红黑树"}).json()
        assert len(hits) == 1, "只应命中本课程的消息"
        hit = hits[0]
        assert hit["conversation_id"] == conversation_id
        assert hit["message_role"] == "user"
        assert "红黑树" in hit["snippet"]
        assert client.get(f"/api/v1/courses/{course_id}/conversations/search", params={"q": "不存在的词"}).json() == []
    finally:
        app.dependency_overrides.clear()
