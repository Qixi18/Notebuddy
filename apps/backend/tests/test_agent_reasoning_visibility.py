"""思维链可见性与「核验后发布」契约。

2026-11-01 复审 P0-QA-02 之后的行为：

- ``run_agent``（进程内）仍然产出带原文的 ``thinking`` 事件，供循环内部使用；
- HTTP 层**不外发**思维链原文，只发一条不带正文的 ``status: thinking``；
- ``delta`` 必须出现在证据门禁状态（``verified`` / ``partially_verified`` /
  ``unverified_no_evidence``）之后；
- 思维链不落库；未核验草稿不会写进会话历史。

两个测试分别守住两段：
1. ``run_agent`` 的 thinking 事件携带 reasoning 原文（内部契约）；
2. HTTP 流里没有原文、正文在门禁之后、``process_json`` 里没有原文。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Conversation, ConversationMessage, Course
from app.main import app
from app.services import agent_execution

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
    assert thinking, "进程内 thinking 事件必须保留原文，供循环与审计使用"
    joined = "".join(str(event.get("text") or "") for event in thinking)
    assert joined == SECRET_COT + "继续思考"
    # 思维链只能走 thinking 通道，不能混进正文增量
    deltas = "".join(str(event.get("text") or "") for event in events if event["type"] == "delta")
    assert SECRET_COT not in deltas
    # 最终回答照常输出
    final = [event for event in events if event["type"] == "final"]
    assert final and final[0]["answer"] == "这是正式回答。"


def test_stream_hides_reasoning_and_publishes_after_gate(tmp_path, monkeypatch):
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
            yield {"type": "delta", "text": "未核验草稿"}
            yield {
                "type": "final", "answer": "正式回答", "chunks": [],
                "web_results": [], "suggestions": [],
            }

        monkeypatch.setattr(agent_execution, "run_agent", fake_run_agent)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/agent-messages",
                json={"question": "问题"},
            )
            assert response.status_code == 200, response.text
            body = response.text
            # 思维链原文与未核验草稿都不外发
            assert SECRET_COT not in body
            assert "未核验草稿" not in body
            # 只有不带正文的 thinking 状态
            assert '"status": "thinking"' in body
            # 正文 delta 必须晚于门禁状态事件
            assert body.index('"status": "unverified_no_evidence"') < body.index('"type": "delta"')
            assert body.index('"type": "delta"') < body.index('"type": "final"')
            assert "正式回答" in body

        with factory() as db:
            assistant = db.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
            ))
            assert assistant is not None
            # 正文与建议里绝不能混入思维链
            assert SECRET_COT not in assistant.content
            assert SECRET_COT not in (assistant.suggestions_json or "")
            # 思维链不落库；只保留计数与耗时
            assert SECRET_COT not in (assistant.process_json or "")
            process = json.loads(assistant.process_json)
            assert process["thinking_chars"] == len(SECRET_COT)
            assert process["verification"]["status"] == "unverified_no_evidence"
            assert isinstance(process.get("thinking_ms"), int)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
