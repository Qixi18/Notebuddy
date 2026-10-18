"""悬浮坞 agent 流式端点（SSE）。

``POST /conversations/{id}/agent-messages``：请求体 ``AgentMessageCreate``，
响应 ``text/event-stream``，逐条 ``data: {json}\\n\\n`` 事件：

- ``step`` / ``delta``：工具时间线与回答增量（原样转发 agent 循环事件）；
- ``final``：收尾（answer + sources + suggestions），随后按现有 evidence 机制落库；
- ``notice`` / ``error``：提示与失败；agent 链路任何失败都会回退旧问答管线
  （``run_answer``），保证无 key、模型异常时用户体验与现有问答一致。

与旧端点的关系：本文件不复用 ``send_message`` 的持久化代码而是等价复刻，
``app/api/v1/conversations.py`` 的旧行为保持零改动。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent_loop import run_agent
from app.ai.evidence import claim_payload, extract_claims
from app.ai.orchestrator import run_answer, source_payload
from app.api.v1.conversations import _load_conversation
from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Conversation,
    ConversationMessage,
    Material,
    MessageEvidence,
    Note,
    SourceRef,
    WebSource,
)
from app.schemas.api import AgentMessageCreate

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _agent_sources(chunks: list, web_results: list[dict]) -> list[dict]:
    """把 agent 收集的证据转换成前端来源卡片结构（与旧链路 sources 同构）。"""
    sources: list[dict] = [source_payload(chunk) for chunk in chunks]
    for item in web_results:
        sources.append({
            "source_type": "web",
            "title": item.get("title"),
            "url": item.get("url"),
            "site_name": item.get("site_name"),
            "snippet": item.get("snippet"),
            "support_level": "supplement",
        })
    return sources


def _persist_assistant_message(
    db: Session,
    *,
    conversation: Conversation,
    learning_goal: str | None,
    content: str,
    model_version: str | None,
    chunks: list,
    web_results: list[dict],
    claims: list[dict],
) -> ConversationMessage:
    """等价复刻旧端点的回答落库：消息 + evidence（课件来源/网络来源/通用解释）。"""
    assistant = ConversationMessage(
        conversation_id=conversation.id, role="assistant", content=content,
        learning_goal=learning_goal, status="completed", model_version=model_version,
    )
    db.add(assistant)
    db.flush()
    for claim in claims:
        claim_key = str(claim.get("claim_key") or "answer")
        linked_source = False
        for chunk_index in claim.get("chunk_indexes", []):
            if not isinstance(chunk_index, int) or not 0 <= chunk_index < len(chunks):
                continue
            chunk = chunks[chunk_index]
            source_ref = db.get(SourceRef, chunk.source_ref_id) if chunk.source_ref_id else None
            if source_ref is None and chunk.page_block_id:
                source_ref = db.scalar(select(SourceRef).where(
                    SourceRef.page_block_id == chunk.page_block_id,
                    SourceRef.status == "active",
                ))
            db.add(MessageEvidence(
                message_id=assistant.id,
                source_ref_id=source_ref.id if source_ref else None,
                claim_key=claim_key,
                evidence_type=str(claim.get("evidence_type") or (
                    "course_direct" if chunk.direct_support else "course_related"
                )),
                support_level="direct" if chunk.direct_support else "related",
            ))
            linked_source = True
        for web_index in claim.get("web_indexes", []):
            if not isinstance(web_index, int) or not 0 <= web_index < len(web_results):
                continue
            item = web_results[web_index]
            source = db.scalar(select(WebSource).where(
                WebSource.course_id == conversation.course_id, WebSource.url == item["url"],
            ))
            if source is not None:
                db.add(MessageEvidence(
                    message_id=assistant.id, web_source_id=source.id,
                    claim_key=claim_key, evidence_type="web_supplement", support_level="supplement",
                ))
                linked_source = True
        if not linked_source:
            db.add(MessageEvidence(
                message_id=assistant.id, claim_key=claim_key,
                evidence_type=str(claim.get("evidence_type") or "general_explanation"),
                support_level=str(claim.get("support_level") or "unverified"),
            ))
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(assistant)
    return assistant


def _fallback_sources(result: dict[str, Any]) -> list[dict]:
    return _agent_sources(result.get("chunks") or [], result.get("web_results") or [])


@router.post("/conversations/{conversation_id}/agent-messages")
def send_agent_message(
    conversation_id: str,
    payload: AgentMessageCreate,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation = _load_conversation(db, conversation_id)
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
    user = ConversationMessage(
        conversation_id=conversation_id, role="user", content=payload.question.strip(),
        learning_goal=payload.learning_goal, status="completed", idempotency_key=payload.idempotency_key,
    )
    db.add(user)
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
            assistant = _persist_assistant_message(
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
                "sources": _agent_sources(chunks, web_results),
                "suggestions": final_event.get("suggestions") or [],
                "message_id": assistant.id,
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
            assistant = _persist_assistant_message(
                db, conversation=conversation, learning_goal=payload.learning_goal,
                content=result["answer"], model_version=result.get("model_version"),
                chunks=result["chunks"], web_results=result["web_results"], claims=claims,
            )
            yield _sse({
                "type": "final",
                "answer": result["answer"],
                "mode": result.get("mode") or "deepseek-rag",
                "model_version": result.get("model_version"),
                "sources": _fallback_sources(result),
                "suggestions": [],
                "message_id": assistant.id,
                "fallback": True,
                "reason": error_message,
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
