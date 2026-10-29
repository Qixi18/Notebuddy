"""思维链（reasoning）不得外发给前端，也不得写入数据库。

背景：集成时 `agent_loop` 曾把模型的 reasoning 增量原样作为 `thinking` 事件外发，
`api/v1/agent.py` 又把它累加进 `process_json` 落库，前端在「过程记录」里展开显示。
本轮改为：只发不带内容的边界信号、只记耗时，工具摘要/状态/耗时与最终回答照常保留。

两个测试分别守住两侧：
1. `run_agent` 逐条事件里不出现思维链原文，且 `thinking` 事件不含 text 字段；
2. 即使上游（或未来改动）把原文塞进事件，HTTP 响应与 `process_json` 里都不得出现。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent as agent_api
from app.db.database import Base, get_db
from app.db.models import Conversation, ConversationMessage, Course
from app.main import app

pytest_plugins = ["tests.notebook_fixtures"]

SECRET_COT = "SECRET-CHAIN-OF-THOUGHT-不要外发"


class _FakeClient:
    """冒充 DeepSeekClient：先吐一段 reasoning，再吐正文。"""

    configured = True

    def chat_stream(self, messages, tools=None, max_tokens=0):
        yield {"type": "reasoning", "text": SECRET_COT}
        yield {"type": "reasoning", "text": "继续思考"}
        yield {"type": "delta", "text": "这是正式回答。"}


def test_run_agent_never_forwards_reasoning_text(session, monkeypatch):
    from app.ai import agent_loop

    monkeypatch.setattr(agent_loop, "DeepSeekClient", _FakeClient)

    events = list(agent_loop.run_agent(
        session, course_id="course-1", course_name="课程", question="问题",
    ))

    thinking = [event for event in events if event["type"] == "thinking"]
    assert thinking, "至少要保留思考边界信号，用于计量耗时"
    for event in thinking:
        assert "text" not in event, event
    # 整个事件流里都不能出现思维链原文
    assert SECRET_COT not in json.dumps(events, ensure_ascii=False)
    assert "继续思考" not in json.dumps(events, ensure_ascii=False)
    # 最终回答照常输出
    final = [event for event in events if event["type"] == "final"]
    assert final and final[0]["answer"] == "这是正式回答。"


def test_stream_and_persistence_ignore_reasoning_text(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'agent.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        with factory() as db:
            course = Course(name="课程")
            db.add(course)
            db.flush()
            conversation = Conversation(
                course_id=course.id, title="会话", default_scope="course", scope="course",
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        def fake_run_agent(*args, **kwargs):
            # 故意带上原文：上层必须无视它
            yield {"type": "thinking", "text": SECRET_COT}
            yield {
                "type": "final", "answer": "正式回答", "chunks": [],
                "web_results": [], "suggestions": [],
            }

        monkeypatch.setattr(agent_api, "run_agent", fake_run_agent)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/agent-messages",
                json={"question": "问题"},
            )
            assert response.status_code == 200, response.text
            assert SECRET_COT not in response.text

        with factory() as db:
            assistant = db.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
            ))
            assert assistant is not None
            assert SECRET_COT not in (assistant.process_json or "")
            assert SECRET_COT not in (assistant.suggestions_json or "")
            assert SECRET_COT not in assistant.content
            if assistant.process_json:
                process = json.loads(assistant.process_json)
                assert "thinking" not in process, "只允许 thinking_ms，不允许 thinking 正文"
                assert isinstance(process.get("thinking_ms"), int)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
