from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Conversation, ConversationMessage
from app.services import agent_execution
from app.services.agent_execution import (
    AgentMessageCommand,
    NotebookContextCommand,
    agent_message_events,
)
from app.services.errors import ApplicationError
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


def _command(notebook_id: str, course_id: str, *, revision: int, key: str) -> AgentMessageCommand:
    return AgentMessageCommand(
        question="解释这一段",
        scope="notebook",
        learning_goal=None,
        material_id=None,
        allow_web=False,
        allow_quiz=False,
        learning_mode="direct",
        idempotency_key=key,
        teacher_persona="vodyanitsa",
        notebook_context=NotebookContextCommand(
            course_id=course_id, notebook_id=notebook_id, revision=revision,
        ),
    )


def test_notebook_revision_conflict_is_rejected_before_user_message_persistence(session):
    course = make_course(session, "课程")
    notebook = make_notebook(session, course, "笔记")
    conversation = Conversation(
        course_id=None, notebook_id=notebook.id, title="新对话",
        scope="notebook", default_scope="notebook",
    )
    session.add(conversation)
    session.commit()

    with pytest.raises(ApplicationError) as error:
        agent_message_events(
            conversation.id,
            _command(notebook.id, course.id, revision=notebook.document_revision + 1, key="stale"),
            session,
        )

    assert error.value.status_code == 409
    assert session.scalar(select(ConversationMessage.id).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == "user",
    )) is None


def test_duplicate_idempotency_key_is_rejected_without_another_turn(session):
    course = make_course(session, "课程")
    notebook = make_notebook(session, course, "笔记")
    conversation = Conversation(
        course_id=None, notebook_id=notebook.id, title="新对话",
        scope="notebook", default_scope="notebook",
    )
    session.add(conversation)
    session.flush()
    session.add(ConversationMessage(
        conversation_id=conversation.id, role="user", content="之前的问题",
        status="completed", idempotency_key="once",
    ))
    session.commit()

    with pytest.raises(ApplicationError) as error:
        agent_message_events(
            conversation.id,
            _command(notebook.id, course.id, revision=notebook.document_revision, key="once"),
            session,
        )

    assert error.value.status_code == 409
    assert session.scalar(select(ConversationMessage.id).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == "user",
    )) is not None
    assert session.scalar(select(ConversationMessage.id).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == "assistant",
    )) is None


def _course_command() -> AgentMessageCommand:
    return AgentMessageCommand(
        question="解释这一段", scope="course", learning_goal=None,
        material_id=None, allow_web=False, allow_quiz=False,
        learning_mode="direct", idempotency_key="disconnect-check",
        teacher_persona="vodyanitsa",
    )


def test_client_disconnect_persists_one_failed_assistant_message(session, monkeypatch):
    course = make_course(session, "课程")
    conversation = Conversation(
        course_id=course.id, notebook_id=None, title="新对话",
        scope="course", default_scope="course",
    )
    session.add(conversation)
    session.commit()

    monkeypatch.setattr(agent_execution, "run_agent", lambda *_args, **_kwargs: iter([
        {"type": "thinking", "text": "server-side only"},
        {"type": "final", "answer": "不会发出的答案"},
    ]))
    stream = agent_message_events(conversation.id, _course_command(), session)
    assert next(stream)["type"] == "status"
    stream.close()

    assistant = session.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == "assistant",
    )).all()
    assert len(assistant) == 1
    assert assistant[0].status == "failed"
    assert assistant[0].failure_type == "ClientDisconnected"
    assert "server-side only" not in assistant[0].content


def test_model_failure_persists_one_failed_assistant_message(session, monkeypatch):
    course = make_course(session, "课程")
    conversation = Conversation(
        course_id=course.id, notebook_id=None, title="新对话",
        scope="course", default_scope="course",
    )
    session.add(conversation)
    session.commit()

    def fail_agent(*_args, **_kwargs):
        raise RuntimeError("provider secret detail")

    def fail_fallback(*_args, **_kwargs):
        raise RuntimeError("fallback secret detail")

    monkeypatch.setattr(agent_execution, "run_agent", fail_agent)
    monkeypatch.setattr(agent_execution, "run_answer", fail_fallback)
    events = list(agent_message_events(conversation.id, _course_command(), session))

    assistant = session.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == "assistant",
    )).all()
    assert len(assistant) == 1
    assert assistant[0].status == "failed"
    assert assistant[0].failure_type == "RuntimeError"
    assert events[-1]["type"] == "error"
    assert "secret detail" not in str(events[-1])
