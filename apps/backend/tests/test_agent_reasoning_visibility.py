"""思维链随 `thinking` 事件外发，并作为 `process.thinking` 落库（落库前截断 2 万字符）。

背景：集成时曾一度改为「只发不带内容的边界信号、不落库原文」。现恢复为可见模式：
- 前端实时展示需要 `thinking` 事件携带原文；
- 历史回看需要原文随 `process_json` 落库。

边界仍然存在：思维链只能走 `thinking` 通道，不得混进回答正文、建议或证据。

两个测试分别守住两段：
1. `run_agent` 的 thinking 事件必须携带 reasoning 原文；
2. HTTP 流与 `process_json` 里能取到同一份原文，且正文里没有它。
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

SECRET_COT = "SECRET-CHAIN-OF-THOUGHT-不要混进正文"


class _FakeClient:
    """冒充 DeepSeekClient：先吐一段 reasoning，再吐正文。"""

    configured = True

    def chat_stream(self, messages, tools=None, max_tokens=0):
        yield {"type": "reasoning", "text": SECRET_COT}
        yield {"type": "reasoning", "text": "继续思考"}
        yield {"type": "delta", "text": "这是正式回答。"}


def test_run_agent_forwards_reasoning_text(session, monkeypatch):
    from app.ai import agent_loop

    monkeypatch.setattr(agent_loop, "DeepSeekClient", _FakeClient)

    events = list(agent_loop.run_agent(
        session, course_id="course-1", course_name="课程", question="问题",
    ))

    thinking = [event for event in events if event["type"] == "thinking"]
    assert thinking, "thinking 事件必须外发，前端实时展示依赖它"
    joined = "".join(str(event.get("text") or "") for event in thinking)
    assert joined == SECRET_COT + "继续思考"
    # 思维链只能走 thinking 通道，不能混进正文增量
    deltas = "".join(str(event.get("text") or "") for event in events if event["type"] == "delta")
    assert SECRET_COT not in deltas
    # 最终回答照常输出
    final = [event for event in events if event["type"] == "final"]
    assert final and final[0]["answer"] == "这是正式回答。"


def test_stream_and_persistence_keep_reasoning_text(tmp_path, monkeypatch):
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
            # 前端实时展示依赖流里有原文
            assert SECRET_COT in response.text

        with factory() as db:
            assistant = db.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
            ))
            assert assistant is not None
            # 正文与建议里绝不能混入思维链
            assert SECRET_COT not in assistant.content
            assert SECRET_COT not in (assistant.suggestions_json or "")
            # 历史回看依赖 process_json 里有原文
            assert assistant.process_json, "思维链必须随过程轨迹落库"
            process = json.loads(assistant.process_json)
            assert process["thinking"] == SECRET_COT
            assert isinstance(process.get("thinking_ms"), int)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
