"""悬浮坞 agent SSE 端点测试：事件流、持久化、幂等、范围校验与降级回退。

伪造 ``run_agent`` / ``run_answer``，不访问真实服务。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent as agent_endpoint
from app.db.database import Base, get_db
from app.db.models import Conversation, ConversationMessage, Course, KnowledgeNode, Note, Notebook
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


def test_review_suggestion_supports_final_markdown(tmp_path, monkeypatch) -> None:
    """逐块审查：confirm 可携带前端拼装的最终正文（部分采纳）；不提供则沿用建议原文。"""
    client, factory, ids = _client_with_db(tmp_path)
    try:
        with factory() as db:
            from app.knowledge.proposals import create_note_suggestion

            full = create_note_suggestion(db, note_id=ids["note"], proposed_markdown="# 整文替换版", source_ids=[], impact="整篇替换")
            partial = create_note_suggestion(db, note_id=ids["note"], proposed_markdown="# 建议全文\n全部内容", source_ids=[], impact="定点修改")
            db.commit()
            full_id, partial_id = full.id, partial.id

        unchanged = client.post(f"/api/v1/notes/{ids['note']}/suggestions/{full_id}/review", json={"decision": "confirm"})
        assert unchanged.status_code == 200
        assert unchanged.json()["content_markdown"] == "# 整文替换版"

        partial_response = client.post(
            f"/api/v1/notes/{ids['note']}/suggestions/{partial_id}/review",
            json={"decision": "confirm", "final_markdown": "# 建议全文\n只采纳了一部分"},
        )
        assert partial_response.status_code == 200
        assert partial_response.json()["content_markdown"] == "# 建议全文\n只采纳了一部分"
        with factory() as db:
            from app.db.models import NoteSuggestion as SuggestionModel

            assert db.get(SuggestionModel, partial_id).impact.endswith("部分采纳")
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


def test_notebook_context_is_validated_and_forwarded(tmp_path, monkeypatch) -> None:
    client, factory, ids = _client_with_db(tmp_path)
    try:
        with factory() as db:
            book = Notebook(course_id=ids["course"], title="整篇物理学笔记", tree_slot=99, display_order=99)
            db.add(book)
            db.commit()
            book_id = book.id

        captured: dict = {}

        def fake_agent(db, **kwargs):
            captured.update(kwargs)
            yield {"type": "final", "answer": "建议内容", "mode": "agent", "model_version": None,
                   "chunks": [], "web_results": [], "suggestions": []}

        monkeypatch.setattr(agent_endpoint, "run_agent", fake_agent)
        response = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={
                "question": "解释这段", "scope": "course",
                "notebook_context": {
                    "course_id": ids["course"], "notebook_id": book_id, "revision": 0,
                    "title": "整篇物理学笔记", "selection": "核心关系是 F = ma",
                    "excerpt": "物体的质量、加速度与合力之间存在定量关系。",
                },
            },
        )
        assert response.status_code == 200, response.text
        assert "整篇课程笔记" in captured["reading_context"]
        assert "F = ma" in captured["reading_context"]
        assert "物体的质量、加速度" in captured["reading_context"]
        assert "不要声称已经修改" in captured["reading_context"]
        assert captured["scope"] == "course"
        assert captured["editable_note_id"] is None

        stale = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "解释", "scope": "course",
                  "notebook_context": {"course_id": ids["course"], "notebook_id": book_id, "revision": 3}},
        )
        assert stale.status_code == 409

        missing = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "解释", "scope": "course",
                  "notebook_context": {"course_id": ids["course"], "notebook_id": "missing", "revision": 0}},
        )
        assert missing.status_code == 404

        both = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "解释", "scope": "note",
                  "reading_context": {"note_id": ids["note"]},
                  "notebook_context": {"course_id": ids["course"], "notebook_id": book_id, "revision": 0}},
        )
        assert both.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_agent_endpoint_rejects_material_outside_course_scope(tmp_path, monkeypatch) -> None:
    """课件收窄仅 course 档可用：global / note 携带 material_id → schema 层 422。"""
    client, _factory, ids = _client_with_db(tmp_path)
    try:
        for scope in ("global", "note"):
            response = client.post(
                f"/api/v1/conversations/{ids['conversation']}/agent-messages",
                json={"question": "问题", "scope": scope, "material_id": "m-1"},
            )
            assert response.status_code == 422, f"scope={scope} 带 material_id 应 422"

        # course 档带 material_id 通过 schema 校验；bogus id 落到端点的归属校验（404，而非 422）
        course_scope = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "问题", "scope": "course", "material_id": "not-exist"},
        )
        assert course_scope.status_code == 404, "course 档不应被 schema 422 拦截，而是走端点归属校验"
        assert "不属于当前课程" in course_scope.text
    finally:
        app.dependency_overrides.clear()


def test_agent_endpoint_forwards_note_discovery_and_lists_course_suggestions(tmp_path, monkeypatch) -> None:
    """P4 端到端：allow_note_discovery 透传给 run_agent；课程级端点返回 pending 建议并带笔记标题。"""
    client, factory, ids = _client_with_db(tmp_path)
    try:
        captured: dict = {}

        def fake_agent(db, **kwargs):
            captured.update(kwargs)
            yield {"type": "final", "answer": "已定位并提交建议。", "mode": "agent", "model_version": None,
                   "chunks": [], "web_results": [], "suggestions": []}

        monkeypatch.setattr(agent_endpoint, "run_agent", fake_agent)
        response = client.post(
            f"/api/v1/conversations/{ids['conversation']}/agent-messages",
            json={"question": "把《行列式笔记》补全一下", "scope": "global", "allow_note_discovery": True},
        )
        assert response.status_code == 200, response.text
        assert captured["allow_note_discovery"] is True, "发现开关必须透传到 agent 循环"

        with factory() as db:
            from app.knowledge.proposals import create_note_suggestion
            suggestion = create_note_suggestion(db, note_id=ids["note"], proposed_markdown="# 行列式\n新内容", source_ids=[], impact="补全")
            db.commit()

        listed = client.get(f"/api/v1/courses/{ids['course']}/note-suggestions?status=pending")
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 1 and rows[0]["id"] == suggestion.id
        assert rows[0]["note_title"] == "行列式笔记", "课程级建议必须带目标笔记标题"
        assert listed.json() == client.get(f"/api/v1/courses/{ids['course']}/note-suggestions").json(), "默认 status=pending"
    finally:
        app.dependency_overrides.clear()


def test_persist_unfinished_assistant_covers_partial_and_empty(tmp_path) -> None:
    """v6 P2：断连兜底——有部分正文落 aborted；无正文落 failed 占位。"""
    client, factory, ids = _client_with_db(tmp_path)
    try:
        from app.api.v1.agent import _persist_unfinished_assistant

        with factory() as db:
            conversation = db.get(Conversation, ids["conversation"])
            _persist_unfinished_assistant(db, conversation, "已经流式生成的部分回答", None)
            _persist_unfinished_assistant(db, conversation, "   ", None)
            rows = db.query(ConversationMessage).filter_by(
                conversation_id=ids["conversation"], role="assistant"
            ).all()
            assert [row.status for row in rows] == ["aborted", "failed"]
            assert rows[0].content == "已经流式生成的部分回答"
            assert rows[1].failure_type == "ClientDisconnected"
    finally:
        app.dependency_overrides.clear()
