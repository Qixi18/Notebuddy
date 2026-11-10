"""思维链可见性与「过程可见 + 核验后落库」契约（ADR-0005，2026-11-06）。

取代 2026-11-01 P0-QA-02 的「过程不可见」口径，保留其落库安全核心：

- ``run_agent``（进程内）产出带原文的 ``thinking`` 事件（内部契约，不变）；
- HTTP 层实时外发思维链原文与门禁前正文 delta（未核验草稿，仅供展示）；
- 草稿已实时下发时不再重复回放门禁后增量；
- 落库正文仍只由证据门禁决定：未核验草稿不写进会话历史正文；
- 思维链原文随 ``process_json`` 落库（截断 20000 字符），历史可回看。

两个测试分别守住两段：
1. ``run_agent`` 的 thinking 事件携带 reasoning 原文（内部契约）；
2. HTTP 流外发思考链与草稿，但落库正文以门禁输出为准、思考链进 process_json。
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


def test_stream_shows_process_and_persists_verified_answer(tmp_path, monkeypatch):
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
            # ADR-0005：思维链原文与门禁前草稿实时外发
            assert SECRET_COT in body
            assert '"type": "thinking"' in body
            assert "未核验草稿" in body
            assert '"status": "thinking"' in body
            # 顺序：thinking → 草稿 delta → 门禁状态 → final
            assert body.index('"type": "thinking"') < body.index('"type": "delta"')
            assert body.index('"type": "delta"') < body.index('"status": "unverified_no_evidence"')
            assert body.index('"type": "delta"') < body.index('"type": "final"')
            # 草稿已实时下发，门禁后不再重复回放
            assert body.count('"type": "delta"') == 1
            assert "正式回答" in body

        with factory() as db:
            assistant = db.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
            ))
            assert assistant is not None
            # 落库正文以门禁输出为准：草稿与思维链都不进正文/建议
            assert assistant.content == "正式回答"
            assert "未核验草稿" not in assistant.content
            assert SECRET_COT not in assistant.content
            assert SECRET_COT not in (assistant.suggestions_json or "")
            # 思维链原文落库（ADR-0005），计数与耗时保留
            assert SECRET_COT in (assistant.process_json or "")
            process = json.loads(assistant.process_json)
            assert process["thinking_chars"] == len(SECRET_COT)
            assert process["thinking"] == SECRET_COT
            assert process["verification"]["status"] == "unverified_no_evidence"
            assert isinstance(process.get("thinking_ms"), int)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
