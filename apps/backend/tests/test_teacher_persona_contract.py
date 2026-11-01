"""Current desktop-pet persona is accepted by every question endpoint."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import agent, conversations
from app.db.database import Base, get_db
from app.db.models import Conversation, Course
from app.main import app
from app.schemas.assistant import AssistantRequest
from app.schemas.conversations import AgentMessageCreate, ConversationMessageCreate


@pytest.mark.parametrize("schema", [AssistantRequest, ConversationMessageCreate, AgentMessageCreate])
@pytest.mark.parametrize("persona", [None, "vodyanitsa"])
def test_question_requests_use_current_persona(schema, persona):
    payload = {"question": "你好"}
    if persona is not None:
        payload["teacher_persona"] = persona
    request = schema.model_validate(payload)
    assert request.teacher_persona == "vodyanitsa"


@pytest.mark.parametrize("schema", [AssistantRequest, ConversationMessageCreate, AgentMessageCreate])
@pytest.mark.parametrize("legacy", ["elf", "doubao", "feiyu"])
def test_legacy_personas_normalize_to_current_pet(schema, legacy):
    request = schema.model_validate({"question": "你好", "teacher_persona": legacy})
    assert request.teacher_persona == "vodyanitsa"


@pytest.mark.parametrize("schema", [AssistantRequest, ConversationMessageCreate, AgentMessageCreate])
def test_unknown_persona_is_still_rejected(schema):
    with pytest.raises(ValidationError):
        schema.model_validate({"question": "你好", "teacher_persona": "not-a-persona"})


@pytest.mark.parametrize("endpoint,status_code", [("messages", 201), ("agent-messages", 200)])
def test_current_persona_can_send_and_read_back_messages(tmp_path, monkeypatch, endpoint, status_code):
    engine = create_engine(f"sqlite:///{(tmp_path / 'persona.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    def answer(*args, **kwargs):
        assert kwargs["teacher_persona"] == "vodyanitsa"
        return {"answer": "你好，我是沃雅妮莎。", "chunks": [], "web_results": []}

    def stream(*args, **kwargs):
        yield {"type": "delta", "text": "你好，我是沃雅妮莎。"}
        yield {"type": "final", **answer(*args, **kwargs), "suggestions": []}

    monkeypatch.setattr(conversations, "run_answer", answer)
    monkeypatch.setattr(agent, "run_agent", stream)
    app.dependency_overrides[get_db] = test_db
    try:
        with factory() as db:
            course = Course(name="人设协议测试课程")
            db.add(course)
            db.flush()
            conversation = Conversation(course_id=course.id, title="新对话", scope="course")
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/{endpoint}",
                json={"question": "你好", "teacher_persona": "vodyanitsa", "allow_web": False},
            )
            assert response.status_code == status_code, response.text
            if endpoint == "agent-messages":
                events = [json.loads(line[6:]) for line in response.text.splitlines()
                          if line.startswith("data: ")]
                assert events[-1]["type"] == "final"
                assert events[-1]["answer"] == "你好，我是沃雅妮莎。"
            else:
                assert response.json()["content"] == "你好，我是沃雅妮莎。"
            history = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()
            assert [(item["role"], item["content"]) for item in history] == [
                ("user", "你好"), ("assistant", "你好，我是沃雅妮莎。"),
            ]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
