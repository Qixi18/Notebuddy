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
import time
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
    Conversation,
    ConversationMessage,
    Material,
    Note,
    Notebook,
)
from app.schemas.api import AgentMessageCreate
from app.services.assistant_sources import sources_from_evidence
from app.services.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    derive_conversation_title,
    persist_assistant_message,
)
from app.services.course_scope import material_in_course

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable_encoder(event), ensure_ascii=False)}\n\n"


def _persist_interrupted_agent(
    db: Session, conversation: Conversation, partial_text: str,
    learning_goal: str | None, process: dict[str, Any] | None,
    suggestions: list[dict[str, Any]] | None = None,
) -> None:
    """Keep the conversation complete when an SSE client disconnects mid-answer."""
    process_json = json.dumps(process, ensure_ascii=False) if process else None
    partial = partial_text.strip()
    if partial:
        row = ConversationMessage(
            conversation_id=conversation.id, role="assistant", content=partial,
            learning_goal=learning_goal, status="aborted", process_json=process_json,
            suggestions_json=json.dumps(suggestions, ensure_ascii=False) if suggestions else None,
        )
    else:
        row = ConversationMessage(
            conversation_id=conversation.id, role="assistant",
            content="本次回答已中断，没有收到内容；请重新提问。",
            learning_goal=learning_goal, status="failed", failure_type="ClientDisconnected",
            process_json=process_json,
            suggestions_json=json.dumps(suggestions, ensure_ascii=False) if suggestions else None,
        )
    db.add(row)
    conversation.updated_at = datetime.now(UTC)
    db.commit()


@router.post("/conversations/{conversation_id}/agent-messages")
def send_agent_message(
    conversation_id: str,
    payload: AgentMessageCreate,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation = ensure_conversation(db, conversation_id)
    course = ensure_course(db, conversation.course_id)
    is_first_turn = not any(message.role == "user" for message in conversation.messages)
    effective_scope = payload.scope if is_first_turn else (
        conversation.scope or conversation.default_scope or "course"
    )
    if not is_first_turn and payload.scope != effective_scope:
        raise HTTPException(409, "本会话的提问范围已锁定，请新建对话后切换范围")

    if payload.idempotency_key:
        existing = db.scalar(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
            ConversationMessage.idempotency_key == payload.idempotency_key,
        ))
        if existing is not None:
            raise HTTPException(status_code=409, detail="该问题已提交过，请勿重复发送")

    selected = db.get(Material, payload.material_id) if payload.material_id else None
    if payload.material_id and (
        selected is None or selected.deleted_at is not None
        or not material_in_course(db, selected, conversation.course_id)
    ):
        raise HTTPException(status_code=404, detail="所选资料不属于当前课程")

    reading = payload.reading_context
    if reading is not None and reading.note_id:
        raise HTTPException(
            status_code=422,
            detail="分节笔记上下文已退役；请使用整篇笔记上下文（notebook_context）",
        )
    notebook_context = payload.notebook_context
    locked_notebook_id = notebook_context.notebook_id if notebook_context else None
    if effective_scope == "note" and not locked_notebook_id:
        raise HTTPException(status_code=422, detail="锁定当前笔记模式需要先打开一本笔记")
    if (not is_first_turn and effective_scope == "note"
            and conversation.note_id != locked_notebook_id):
        legacy_note = db.get(Note, conversation.note_id) if conversation.note_id else None
        if legacy_note is None or legacy_note.notebook_id != locked_notebook_id:
            raise HTTPException(409, "本会话锁定的笔记与当前笔记不一致，请新建对话")
        # Older conversations stored a Note ID. Upgrade the compatibility field
        # only after proving that the legacy Note belongs to the supplied Notebook.
        conversation.note_id = locked_notebook_id

    notebook_title = ""
    if notebook_context is not None:
        book = db.get(Notebook, notebook_context.notebook_id)
        if (book is None or book.deleted_at is not None
                or book.course_id != conversation.course_id
                or notebook_context.course_id != conversation.course_id):
            raise HTTPException(status_code=404, detail="正在编辑的笔记不存在或无法访问")
        if book.document_revision != notebook_context.revision:
            raise HTTPException(status_code=409, detail="笔记正文已更新，请刷新上下文后重新提问")
        notebook_title = (notebook_context.title or book.title or "未命名笔记")[:200]

    history = [(message.role, message.content) for message in conversation.messages]
    user = ConversationMessage(
        conversation_id=conversation_id, role="user", content=payload.question.strip(),
        learning_goal=payload.learning_goal, status="completed", idempotency_key=payload.idempotency_key,
    )
    db.add(user)
    # 范围是会话级属性：仅首轮落库，之后沿用建会话时的范围（与 /messages 一致）
    if is_first_turn:
        new_scope = effective_scope
        conversation.default_scope = new_scope
        conversation.scope = new_scope
        if new_scope == "note":
            conversation.note_id = locked_notebook_id
            conversation.note_title = notebook_title or (reading.note_title if reading else None) or conversation.note_title
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
    elif notebook_context is not None:
        parts = [f"《{notebook_title}》（整篇课程笔记，revision {notebook_context.revision}）"]
        if notebook_context.selection:
            parts.append(f"用户选中的原文：\n{notebook_context.selection}")
        if notebook_context.excerpt:
            parts.append(f"选区附近的正文：\n{notebook_context.excerpt}")
        parts.append("这段内容来自用户正在编辑的文档。回答只作为建议，用户会决定是否插入；"
                     "不要声称已经修改了笔记，也不要编造未提供的上下文。")
        reading_section = "\n".join(parts)

    def event_stream() -> Iterator[str]:
        final_event: dict[str, Any] | None = None
        error_message: str | None = None
        partial_text: list[str] = []
        completed_suggestions: list[dict[str, Any]] = []
        persisted = False
        process: dict[str, Any] = {"thinking_ms": 0, "steps": []}
        thinking_started: float | None = None

        def close_thinking() -> None:
            nonlocal thinking_started
            if thinking_started is not None:
                process["thinking_ms"] += int((time.monotonic() - thinking_started) * 1000)
                thinking_started = None

        def persist_interrupted() -> None:
            nonlocal persisted
            if persisted:
                return
            close_thinking()
            # 只保留工具摘要/状态/耗时；思维链原文从不进入判断与落库。
            process["steps"] = [
                {key: value for key, value in step.items() if key != "started"}
                for step in process["steps"][:60]
            ]
            trace = process if process["thinking_ms"] or process["steps"] else None
            _persist_interrupted_agent(
                db, conversation, "".join(partial_text), payload.learning_goal, trace,
                completed_suggestions,
            )
            persisted = True

        try:
            for event in run_agent(
                db,
                course_id=conversation.course_id,
                course_name=course.name,
                question=payload.question,
                scope=effective_scope,
                locked_notebook_id=locked_notebook_id if effective_scope == "note" else None,
                editable_notebook_id=locked_notebook_id,
                reading_context=reading_section,
                material_id=payload.material_id,
                allow_web=payload.allow_web,
                allow_quiz=payload.allow_quiz,
                learning_mode=payload.learning_mode,
                learning_goal=payload.learning_goal,
                history=history,
                teacher_persona=payload.teacher_persona,
                conversation_id=conversation.id,
            ):
                if event["type"] == "final":
                    close_thinking()
                    final_event = event
                elif event["type"] == "error":
                    close_thinking()
                    error_message = str(event.get("message") or "agent 执行失败")
                else:
                    if event["type"] == "thinking":
                        # 只记开始时间用于算耗时；同时把事件重建成不带内容的信号，
                        # 避免下游把任何随行的思维链原文原样透传给前端。
                        if thinking_started is None:
                            thinking_started = time.monotonic()
                        event = {"type": "thinking"}
                    elif event["type"] == "delta":
                        close_thinking()
                        partial_text.append(str(event.get("text") or ""))
                    elif event["type"] == "step":
                        close_thinking()
                        if event.get("status") == "done":
                            suggestions = event.get("suggestions")
                            if isinstance(suggestions, list):
                                completed_suggestions.extend(
                                    item for item in suggestions if isinstance(item, dict)
                                )
                                # Keep these references server-side for disconnect recovery;
                                # the final event remains the only client card payload.
                                event.pop("suggestions", None)
                        if event.get("status") == "running":
                            process["steps"].append({
                                "tool": str(event.get("tool") or ""),
                                "detail": str(event.get("detail") or ""),
                                "started": time.monotonic(),
                            })
                        else:
                            for step in reversed(process["steps"]):
                                if step.get("tool") == event.get("tool") and "duration_ms" not in step:
                                    started = step.pop("started", None)
                                    step["duration_ms"] = (
                                        int((time.monotonic() - started) * 1000)
                                        if started is not None else None
                                    )
                                    if event.get("detail"):
                                        step["detail"] = str(event["detail"])
                                    event["duration_ms"] = step["duration_ms"]
                                    break
                            else:
                                process["steps"].append({
                                    "tool": str(event.get("tool") or ""),
                                    "detail": str(event.get("detail") or ""),
                                    "duration_ms": None,
                                })
                    yield _sse(event)
        except GeneratorExit:
            try:
                persist_interrupted()
            except Exception:
                db.rollback()
            raise
        except Exception as exc:  # 流内异常必须降级为错误事件，不能断流
            close_thinking()
            error_message = f"{type(exc).__name__}: {exc}"

        chunks: list = []
        web_results: list[dict] = []
        if final_event is not None and str(final_event.get("answer") or "").strip():
            chunks = final_event.get("chunks") or []
            web_results = final_event.get("web_results") or []
            claims = [claim_payload(claim) for claim in extract_claims(str(final_event["answer"]), chunks, web_results)]
            process["steps"] = [
                {key: value for key, value in step.items() if key != "started"}
                for step in process["steps"][:60]
            ]
            saved_process = process if process["thinking_ms"] or process["steps"] else None
            assistant = persist_assistant_message(
                db, conversation=conversation, learning_goal=payload.learning_goal,
                content=str(final_event["answer"]), model_version=final_event.get("model_version"),
                chunks=chunks, web_results=web_results,
                claims=claims or [{
                    "claim_key": "answer",
                    "chunk_indexes": list(range(len(chunks))),
                    "web_indexes": list(range(len(web_results))),
                }],
                process=saved_process,
                suggestions=final_event.get("suggestions") or None,
            )
            persisted = True
            yield _sse({
                "type": "final",
                "answer": final_event["answer"],
                "mode": "agent",
                "model_version": final_event.get("model_version"),
                "sources": sources_from_evidence(db, assistant),
                "suggestions": final_event.get("suggestions") or [],
                "message_id": assistant.id,
                "process": assistant.process,
                "conversation_title": conversation.title,
            })
            return

        # agent 链路失败：回退旧问答管线（无 key / 模型异常 / 轮次超限时用户无感）
        try:
            yield _sse({"type": "notice", "text": "智能模式暂不可用，已切换到标准问答。"})
        except GeneratorExit:
            try:
                persist_interrupted()
            except Exception:
                db.rollback()
            raise
        fallback_question = payload.question
        if reading_section:
            fallback_question = f"{fallback_question}\n\n【当前上下文】\n{reading_section}"
        try:
            result = run_answer(
                db,
                course_id=conversation.course_id,
                course_name=course.name,
                question=fallback_question,
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
            persisted = True
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
            persisted = True
            yield _sse({"type": "error", "message": f"问答执行失败（{type(exc).__name__}），请稍后重试"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
