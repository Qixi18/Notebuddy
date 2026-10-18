"""悬浮坞 agent SSE 端点测试：事件流、持久化、幂等、范围校验与降级回退。

伪造 ``run_agent`` / ``run_answer``，不访问真实服务。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent as agent_endpoint
from app.db.database import Base, get_db
from app.db.models import Conversation, ConversationMessage, Course, KnowledgeNode, Note
from app.main import app


def _client_with_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'agent.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    client = TestClient(app)
    with factory() as db:
        course = Course(name="线性代数")
        db.add(course)
        db.flush()
        node = KnowledgeNode(course_id=course.id, name="行列式")
        db.add(node)
        db.flush()
        note = Note(course_id=course.id, knowledge_node_id=node.id, title="行列式笔记", content_markdown="# 行列式")
        db.add(note)
        db.flush()
        conversation = Conversation(course_id=course.id, title="新对话", default_scope="course")
        db.add(conversation)
        db.commit()
        ids = {"course": course.id, "note": note.id, "conversation": conversation.id}
    return client, factory, ids


def _fake_run_agent(events):
    def fake(db, **kwargs):
        yield from events

    return fake


def test_agent_endpoint_streams_persists_and_collects_suggestions(tmp_path, monkeypatch) -> None:
    client, factory, ids = _client_with_db(tmp_path)
    try:
        monkeypatch.setattr(agent_endpoint, "run_agent", _fake_run_agent([
            {"type": "step", "tool": "search_course", "detail": "检索「行列式」", "status": "running"},
            {"type": "delta", "text": "行列式是对角线法则。"},
            {"type": "final", "answer": "行列式是对角线法则。", "mode": "agent", "model_version": "agent-test",
             "chunks": [], "web_results": [], "suggestions": [
                 {"type": "note_suggestion", "id": "sug-1", "note_id": ids["note"], "note_title": "行列式笔记", "impact": "整理"},
             ]},
        ]))
        response = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "整理这篇笔记", "scope": "note", "idempotency_key": "k1",
                  "reading_context": {"note_id": ids["note"], "note_title": "行列式笔记"}},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"type": "step"' in response.text.replace(" ", " ") or '"type":"step"' in response.text
        assert "行列式是对角线法则。" in response.text
        assert '"fallback"' not in response.text

        with factory() as db:
            roles = [m.role for m in db.query(ConversationMessage).filter_by(conversation_id=ids["conversation"]).all()]
            assert roles == ["user", "assistant"], "提问与回答都应落库"
            # 建议行由真实工具在 agent 循环内创建（已在 test_agent_loop 覆盖）；
            # 本测试伪造 run_agent，只验证事件流与消息持久化。
    finally:
        app.dependency_overrides.clear()


def test_agent_endpoint_falls_back_to_legacy_pipeline_on_error(tmp_path, monkeypatch) -> None:
    client, factory, ids = _client_with_db(tmp_path)
    try:
        monkeypatch.setattr(agent_endpoint, "run_agent", _fake_run_agent([
            {"type": "error", "message": "AI 模型未配置"},
        ]))
        monkeypatch.setattr(agent_endpoint, "run_answer", lambda db, **kwargs: {
            "answer": "标准模式回答", "chunks": [], "web_results": [], "claims": [],
            "mode": "persona-general", "model_version": None,
        })
        response = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题"},
        )
        assert response.status_code == 200
        assert "标准模式回答" in response.text
        assert '"fallback": true' in response.text.replace(" ", " ") or '"fallback":true' in response.text
        with factory() as db:
            assistant = db.query(ConversationMessage).filter_by(role="assistant").one()
            assert assistant.content == "标准模式回答"
    finally:
        app.dependency_overrides.clear()


def test_agent_endpoint_rejects_duplicate_idempotency_key(tmp_path, monkeypatch) -> None:
    client, _factory, ids = _client_with_db(tmp_path)
    try:
        monkeypatch.setattr(agent_endpoint, "run_agent", _fake_run_agent([
            {"type": "final", "answer": "第一次回答", "mode": "agent", "model_version": None,
             "chunks": [], "web_results": [], "suggestions": []},
        ]))
        first = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "idempotency_key": "dup"},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "idempotency_key": "dup"},
        )
        assert second.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_agent_endpoint_validates_scope_and_note_ownership(tmp_path, monkeypatch) -> None:
    client, _factory, ids = _client_with_db(tmp_path)
    try:
        locked_without_note = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "scope": "note"},
        )
        assert locked_without_note.status_code == 422

        foreign_note = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "scope": "note", "reading_context": {"note_id": "not-exist"}},
        )
        assert foreign_note.status_code == 404

        monkeypatch.setattr(agent_endpoint, "run_agent", _fake_run_agent([
            {"type": "final", "answer": "全局回答", "mode": "agent", "model_version": None,
             "chunks": [], "web_results": [], "suggestions": []},
        ]))
        global_scope = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "scope": "global"},
        )
        assert global_scope.status_code == 200 and "全局回答" in global_scope.text
    finally:
        app.dependency_overrides.clear()
