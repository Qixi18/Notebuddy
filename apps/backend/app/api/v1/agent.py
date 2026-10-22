"""悬浮坞 agent 流式端点（SSE）。

``POST /conversations/{id}/agent-messages``：请求体 ``AgentMessageCreate``，
响应 ``text/event-stream``，逐条 ``data: {json}\\n\\n`` 事件：

- ``step`` / ``delta``：工具时间线与回答增量（原样转发 agent 循环事件）；
- ``final``：收尾（answer + sources + suggestions），随后按现有 evidence 机制落库；
- ``notice`` / ``error``：提示与失败；agent 链路任何失败都会回退旧问答管线
  （``run_answer``），保证无 key、模型异常时用户体验与现有问答一致。

与传统问答入口共用会话消息及证据持久化服务；SSE 事件仍由本路由管理。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent_loop import run_agent
from app.ai.evidence import claim_payload, extract_claims
from app.ai.orchestrator import run_answer
from app.api.v1.shared import ensure_conversation, ensure_course
from app.db.database import get_db
from app.db.models import (
    ConversationMessage,
    Material,
    Note,
)
from app.schemas.api import AgentMessageCreate
from app.services.assistant_sources import sources_from_evidence
from app.services.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    derive_conversation_title,
    persist_assistant_message,
)

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable_encoder(event), ensure_ascii=False)}\n\n"


@router.post("/conversations/{conversation_id}/agent-messages")
def send_agent_message(
    conversation_id: str,
    payload: AgentMessageCreate,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation = ensure_conversation(db, conversation_id)
    course = ensure_course(db, conversation.course_id)

    if payload.idempotency_key:
        existing = db.scalar(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
            ConversationMessage.idempotency_key == payload.idempotency_key,
        ))
        if existing is not None:
            raise HTTPException(status_code=409, detail="该问题已提交过，请勿重复发送")

    selected = db.get(Material, payload.material_id) if payload.material_id else None
    if payload.material_id and (selected is None or selected.course_id != conversation.course_id or selected.deleted_at is not None):
        raise HTTPException(status_code=404, detail="所选资料不属于当前课程")

    reading = payload.reading_context
    reading_note_id = reading.note_id if reading else None
    if reading_note_id:
        note = db.get(Note, reading_note_id)
        if note is None or note.course_id != conversation.course_id:
            raise HTTPException(status_code=404, detail="正在阅读的笔记不属于当前课程")
    if payload.scope == "note" and not reading_note_id:
        raise HTTPException(status_code=422, detail="锁定当前笔记模式需要先打开一篇笔记")

    history = [(message.role, message.content) for message in conversation.messages]
    is_first_turn = not any(message.role == "user" for message in conversation.messages)
    user = ConversationMessage(
        conversation_id=conversation_id, role="user", content=payload.question.strip(),
        learning_goal=payload.learning_goal, status="completed", idempotency_key=payload.idempotency_key,
    )
    db.add(user)
    # 范围是会话级属性：仅首轮落库，之后沿用建会话时的范围（与 /messages 一致）
    if is_first_turn:
        new_scope = payload.scope or "course"
        conversation.default_scope = new_scope
        conversation.scope = new_scope
        if new_scope == "note":
            conversation.note_id = reading_note_id
            conversation.note_title = (reading.note_title if reading else None) or conversation.note_title
        else:
            conversation.note_id = None
            conversation.note_title = None
    if conversation.title.strip() == DEFAULT_CONVERSATION_TITLE:
        conversation.title = derive_conversation_title(payload.question, conversation.scope, conversation.note_title)
    conversation.updated_at = datetime.now(UTC)
    db.commit()

    reading_section = ""
    if reading is not None:
        parts = [f"《{reading.note_title or '未命名笔记'}》"]
        if reading.section_title:
            parts.append(f"当前小节：{reading.section_title}")
        if reading.excerpt:
            parts.append(f"正文节选：\n{reading.excerpt}")
        reading_section = "\n".join(parts)

    def event_stream() -> Iterator[str]:
        final_event: dict[str, Any] | None = None
        error_message: str | None = None
        try:
            for event in run_agent(
                db,
                course_id=conversation.course_id,
                course_name=course.name,
                question=payload.question,
                scope=payload.scope,
                locked_note_id=reading_note_id if payload.scope == "note" else None,
                editable_note_id=reading_note_id,
                reading_context=reading_section,
                material_id=payload.material_id,
                allow_web=payload.allow_web,
                learning_goal=payload.learning_goal,
                history=history,
                teacher_persona=payload.teacher_persona,
            ):
                if event["type"] == "final":
                    final_event = event
                elif event["type"] == "error":
                    error_message = str(event.get("message") or "agent 执行失败")
                else:
                    yield _sse(event)
        except Exception as exc:  # 流内异常必须降级为错误事件，不能断流
            error_message = f"{type(exc).__name__}: {exc}"

        chunks: list = []
        web_results: list[dict] = []
        if final_event is not None and str(final_event.get("answer") or "").strip():
            chunks = final_event.get("chunks") or []
            web_results = final_event.get("web_results") or []
            claims = [claim_payload(claim) for claim in extract_claims(str(final_event["answer"]), chunks, web_results)]
            assistant = persist_assistant_message(
                db, conversation=conversation, learning_goal=payload.learning_goal,
                content=str(final_event["answer"]), model_version=final_event.get("model_version"),
                chunks=chunks, web_results=web_results,
                claims=claims or [{
                    "claim_key": "answer",
                    "chunk_indexes": list(range(len(chunks))),
                    "web_indexes": list(range(len(web_results))),
                }],
            )
            yield _sse({
                "type": "final",
                "answer": final_event["answer"],
                "mode": "agent",
                "model_version": final_event.get("model_version"),
                "sources": sources_from_evidence(db, assistant),
                "suggestions": final_event.get("suggestions") or [],
                "message_id": assistant.id,
                "conversation_title": conversation.title,
            })
            return

        # agent 链路失败：回退旧问答管线（无 key / 模型异常 / 轮次超限时用户无感）
        yield _sse({"type": "notice", "text": "智能模式暂不可用，已切换到标准问答。"})
        try:
            result = run_answer(
                db,
                course_id=conversation.course_id,
                course_name=course.name,
                question=payload.question,
                material_id=payload.material_id,
                allow_web=payload.allow_web,
                learning_goal=payload.learning_goal,
                history=history,
                teacher_persona=payload.teacher_persona,
            )
            claims = result.get("claims") or [{
                "claim_key": "answer",
                "chunk_indexes": list(range(len(result["chunks"]))),
                "web_indexes": list(range(len(result["web_results"]))),
            }]
            assistant = persist_assistant_message(
                db, conversation=conversation, learning_goal=payload.learning_goal,
                content=result["answer"], model_version=result.get("model_version"),
                chunks=result["chunks"], web_results=result["web_results"], claims=claims,
            )
            yield _sse({
                "type": "final",
                "answer": result["answer"],
                "mode": result.get("mode") or "deepseek-rag",
                "model_version": result.get("model_version"),
                "sources": sources_from_evidence(db, assistant),
                "suggestions": [],
                "message_id": assistant.id,
                "fallback": True,
                "reason": error_message,
                "conversation_title": conversation.title,
            })
        except Exception as exc:
            db.rollback()
            failed = ConversationMessage(
                conversation_id=conversation_id, role="assistant",
                content="本次回答未完成，已保留失败状态；请稍后重试或查看课程检索片段。",
                learning_goal=payload.learning_goal, status="failed", failure_type=type(exc).__name__,
            )
            db.add(failed)
            conversation.updated_at = datetime.now(UTC)
            db.commit()
            yield _sse({"type": "error", "message": f"问答执行失败（{type(exc).__name__}），请稍后重试"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
