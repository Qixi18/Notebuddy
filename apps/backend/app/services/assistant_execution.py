"""Conversation answer use case: coordinate retrieval, verification and persistence."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.notebook_qa import claims_for_answer, run_notebook_answer
from app.ai.orchestrator import run_answer
from app.ai.verified_answer import verify_answer
from app.db.models import Conversation, ConversationMessage, Course
from app.services.conversations import (
    conversation_for_message,
    idempotent_assistant_message,
    material_for_conversation,
    normalize_conversation_scope,
    notebook_for_conversation,
    persist_assistant_message,
    record_failed_assistant_message,
    record_user_turn,
)
from app.services.errors import ApplicationError


def send_conversation_message(
    db: Session,
    conversation_id: str,
    *,
    question: str,
    learning_goal: str | None,
    idempotency_key: str | None,
    allow_web: bool,
    notebook_context: dict | None = None,
    material_id: str | None = None,
    page_number: int | None = None,
    scope: str | None = None,
    note_id: str | None = None,
    note_title: str | None = None,
    teacher_persona: str | None = None,
) -> tuple[Conversation, ConversationMessage]:
    """Run the complete persisted-message use case for either conversation scope."""
    conversation = conversation_for_message(db, conversation_id)
    existing = idempotent_assistant_message(db, conversation_id, idempotency_key)
    if existing is not None:
        return conversation, existing

    if conversation.scope == "notebook":
        context = notebook_context or {}
        notebook_for_conversation(db, conversation, context)
        if material_id or page_number:
            raise ApplicationError(422, "Notebook 答疑不接受课程资料或页码覆盖范围")
        history = record_user_turn(
            db, conversation, question=question, learning_goal=learning_goal,
            idempotency_key=idempotency_key, scope=scope,
            note_id=note_id, note_title=note_title,
        )
        answer = execute_conversation_answer(
            db, conversation, question=question, history=history,
            learning_goal=learning_goal, allow_web=allow_web,
            notebook_revision=context["revision"],
        )
        return conversation, answer

    material_for_conversation(db, conversation, material_id)
    history = record_user_turn(
        db, conversation, question=question, learning_goal=learning_goal,
        idempotency_key=idempotency_key,
        scope=normalize_conversation_scope(scope or conversation.scope),
        note_id=note_id, note_title=note_title,
    )
    answer = execute_conversation_answer(
        db, conversation, question=question, history=history,
        learning_goal=learning_goal, allow_web=allow_web,
        material_id=material_id, page_number=page_number,
        teacher_persona=teacher_persona,
    )
    return conversation, answer


def execute_conversation_answer(
    db: Session,
    conversation: Conversation,
    *,
    question: str,
    history: list[tuple[str, str]],
    learning_goal: str | None,
    allow_web: bool,
    material_id: str | None = None,
    page_number: int | None = None,
    teacher_persona: str | None = None,
    notebook_revision: int | None = None,
) -> ConversationMessage:
    """Run the appropriate answer pipeline and persist either success or failure."""
    notebook_scope = conversation.scope == "notebook"
    course = None
    if not notebook_scope:
        course = db.get(Course, conversation.course_id) if conversation.course_id else None
        if course is None or course.deleted_at is not None:
            raise ApplicationError(404, "课程不存在")
    try:
        if notebook_scope:
            if conversation.notebook_id is None or notebook_revision is None:
                raise ApplicationError(409, "Notebook 会话缺少有效正文版本")
            result = None
            for event in run_notebook_answer(
                db, notebook_id=conversation.notebook_id, revision=notebook_revision,
                question=question, history=history, allow_web=allow_web,
            ):
                if event["type"] == "verified_result":
                    result = event["result"]
            if result is None:
                raise RuntimeError("核验服务未产生最终结果")
            return persist_assistant_message(
                db, conversation=conversation, learning_goal=learning_goal,
                content=result.answer, model_version=result.model_version,
                chunks=result.chunks, web_results=result.web_results,
                claims=claims_for_answer(result), process=result.process,
            )

        assert course is not None
        result = run_answer(
            db, course_id=conversation.course_id, course_name=course.name,
            question=question, material_id=material_id, page_number=page_number,
            allow_web=allow_web, learning_goal=learning_goal, history=history,
            teacher_persona=teacher_persona,
        )
        verified = verify_answer(
            db, answer=str(result["answer"]), chunks=result["chunks"],
            web_results=result["web_results"], course_id=conversation.course_id,
            scope=conversation.scope or "course",
        )
        claims = verified.claims or [{
            "claim_key": "answer", "chunk_indexes": list(range(len(verified.chunks))),
            "web_indexes": list(range(len(result["web_results"]))),
        }]
        return persist_assistant_message(
            db, conversation=conversation, learning_goal=learning_goal,
            content=verified.answer, model_version=result.get("model_version"),
            chunks=verified.chunks, web_results=result["web_results"], claims=claims,
            process={"verification": verified.verification},
        )
    except Exception as exc:
        return record_failed_assistant_message(
            db, conversation, learning_goal=learning_goal,
            failure_type=type(exc).__name__, notebook_scope=notebook_scope,
        )
