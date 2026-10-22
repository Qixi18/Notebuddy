"""First-message naming + first-turn scope application for conversations.

覆盖：默认「新对话」在首条问题后被命名；范围（scope）仅在会话尚无
用户消息时落库，把自动建的空会话改写成用户实际选择；此后忽略 scope 变化。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent, conversations
from app.db.database import Base, get_db
from app.db.models import Conversation, Course
from app.main import app
from app.services.conversations import DEFAULT_CONVERSATION_TITLE, derive_conversation_title


def _setup(tmp_path, title: str = DEFAULT_CONVERSATION_TITLE):
    engine = create_engine(f"sqlite:///{(tmp_path / 'naming.sqlite3').as_posix()}")
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
        conversation = Conversation(course_id=course.id, title=title)
        db.add(conversation)
        db.commit()
        ids = (course.id, conversation.id)
    return TestClient(app), factory, ids


def _fake_answer() -> dict:
    return {
        "answer": "回答", "chunks": [], "web_results": [],
        "claims": [{"claim_key": "answer", "chunk_indexes": [], "web_indexes": []}],
        "model_version": "test-model",
    }


def test_derive_title_prefixes_only_special_scopes_and_truncates() -> None:
    # 整门课程最常见：不加前缀
    assert derive_conversation_title("什么是红黑树？", "course", None) == "什么是红黑树？"
    # 全局可查 / 锁定笔记加前缀，便于历史区分
    assert derive_conversation_title("问题", "global", None) == "全局可查 · 问题"
    assert derive_conversation_title("问题", "note", "红黑树笔记") == "红黑树笔记 · 问题"
    # 笔记标题缺失时退到「锁定笔记」
    assert derive_conversation_title("问题", "note", None) == "锁定笔记 · 问题"
    # 超长按前 18 字截断并加省略号
    long = "请详细解释一下红黑树的五个不变量分别是什么以及如何证明它们"
    derived = derive_conversation_title(long, "course", None)
    assert derived.endswith("…")
    assert len(derived) == 19  # 18 字 + 省略号
    # 压缩内部空白
    assert derive_conversation_title("  a   b  ", "course", None) == "a b"


def test_first_message_renames_and_applies_scope(tmp_path, monkeypatch) -> None:
    client, _factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        monkeypatch.setattr(conversations, "run_answer", lambda *_a, **_k: _fake_answer())
        # 答疑页自动建的是「新对话」course 会话；首轮提问携带用户实际选择的范围
        response = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={
            "question": "红黑树的五个不变量是什么",
            "scope": "note", "note_id": "n-1", "note_title": "红黑树的五个不变量",
        })
        assert response.status_code == 201, response.text
        assert response.json()["conversation_title"] == "红黑树的五个不变量 · 红黑树的五个不变量是什么"

        listed = client.get(f"/api/v1/courses/{course_id}/conversations").json()
        item = next(row for row in listed if row["id"] == conversation_id)
        assert item["title"] == "红黑树的五个不变量 · 红黑树的五个不变量是什么"
        assert item["scope"] == "note"
        assert item["note_id"] == "n-1"
        assert item["note_title"] == "红黑树的五个不变量"
    finally:
        app.dependency_overrides.clear()


def test_second_message_keeps_title_and_ignores_scope_change(tmp_path, monkeypatch) -> None:
    client, _factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        monkeypatch.setattr(conversations, "run_answer", lambda *_a, **_k: _fake_answer())
        client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"question": "第一问"})
        # 中途改范围 + 换问题：会话已有用户消息，scope 与标题都不应变
        second = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={
            "question": "第二问完全不同的问题", "scope": "global",
        })
        assert second.status_code == 201
        assert second.json()["conversation_title"] == "第一问"

        item = next(row for row in client.get(f"/api/v1/courses/{course_id}/conversations").json()
                    if row["id"] == conversation_id)
        assert item["title"] == "第一问"
        assert item["scope"] == "course"
    finally:
        app.dependency_overrides.clear()


def test_agent_transport_renames_too(tmp_path, monkeypatch) -> None:
    client, _factory, (course_id, conversation_id) = _setup(tmp_path)
    try:
        def run_agent(*_a, **_k) -> Iterator[dict]:
            yield {"type": "final", **_fake_answer(), "mode": "agent", "suggestions": []}

        monkeypatch.setattr(agent, "run_agent", run_agent)
        streamed = client.post(f"/api/v1/conversations/{conversation_id}/agent-messages", json={"question": "从桌宠问的一个问题"})
        assert streamed.status_code == 200, streamed.text
        assert '"conversation_title": "从桌宠问的一个问题"' in streamed.text
        item = next(row for row in client.get(f"/api/v1/courses/{course_id}/conversations").json()
                    if row["id"] == conversation_id)
        assert item["title"] == "从桌宠问的一个问题"
    finally:
        app.dependency_overrides.clear()
