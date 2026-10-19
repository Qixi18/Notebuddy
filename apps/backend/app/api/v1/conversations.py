from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.orchestrator import run_answer
from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Conversation,
    ConversationMessage,
    Material,
    MessageEvidence,
    PageBlock,
    SourceRef,
)
from app.schemas.api import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationMessageRead,
    ConversationRead,
    MessageEvidenceRead,
)
from app.services.assistant_sources import sources_from_evidence
from app.services.conversations import load_conversation, persist_assistant_message

router = APIRouter()


def _mode_from_evidence(message: ConversationMessage) -> str:
    """反推回答模式，取值与 ``app.ai.orchestrator`` 返回的 mode 对齐。

    落库字段只有 evidence 与 model_version，因此按「证据类型 + 模型版本」还原：
    有课件/网络证据即 RAG；只有 general_explanation 时，有模型版本说明走的是
    人设通用分支（persona-general），没有则说明模型当时不可用（no-evidence）。
    """
    if message.status == "failed":
        return "failed"
    if message.model_version and message.model_version.startswith("agent"):
        # agent 循环产出的回答；旧消息不会有该前缀，行为不变
        return "agent"
    if message.model_version == "keyword-or-hybrid-fallback":
        return "local-retrieval-fallback"
    evidence_types = {item.evidence_type for item in message.evidence}
    if evidence_types & {"course_direct", "course_related", "web_supplement"}:
        return "deepseek-rag"
    if "general_explanation" in evidence_types:
        return "persona-general" if message.model_version else "no-evidence"
    return ""


def _message_read(db: Session, message: ConversationMessage) -> ConversationMessageRead:
    evidence = []
    for item in message.evidence:
        snippet = None
        location_label = None
        if item.source_ref is not None:
            snippet = item.source_ref.quote
            if item.source_ref.page_block is not None:
                location_label = item.source_ref.page_block.location_label or item.source_ref.page_block.page.location_label
        elif item.web_source is not None:
            snippet = item.web_source.snippet
        evidence.append(MessageEvidenceRead(
            id=item.id,
            claim_key=item.claim_key,
            evidence_type=item.evidence_type,
            support_level=item.support_level,
            source_ref_id=item.source_ref_id,
            web_source_id=item.web_source_id,
            snippet=snippet,
            location_label=location_label,
        ))
    return ConversationMessageRead(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        learning_goal=message.learning_goal,
        status=message.status,
        model_version=message.model_version,
        failure_type=message.failure_type,
        created_at=message.created_at,
        evidence=evidence,
        mode=_mode_from_evidence(message),
        sources=sources_from_evidence(db, message),
    )


@router.post("/courses/{course_id}/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(course_id: str, payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    ensure_course(db, course_id)
    conversation = Conversation(course_id=course_id, title=payload.title.strip(), default_scope=payload.default_scope)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationRead])
def list_conversations(course_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    ensure_course(db, course_id)
    return list(db.scalars(select(Conversation).where(Conversation.course_id == course_id).order_by(Conversation.updated_at.desc())).all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageRead])
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[ConversationMessageRead]:
    load_conversation(db, conversation_id)
    messages = list(db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
        .options(
            selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.source_ref)
            .selectinload(SourceRef.page_block).selectinload(PageBlock.page),
            selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.web_source),
        ).order_by(ConversationMessage.created_at)
    ).all())
    return [_message_read(db, message) for message in messages]


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageRead, status_code=201)
def send_message(
    conversation_id: str,
    payload: ConversationMessageCreate,
    db: Session = Depends(get_db),
) -> ConversationMessageRead:
    conversation = load_conversation(db, conversation_id)
    if payload.idempotency_key:
        existing = db.scalar(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
            ConversationMessage.idempotency_key == payload.idempotency_key,
        ))
        if existing is not None:
            answer = db.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
                ConversationMessage.created_at >= existing.created_at,
            ).order_by(ConversationMessage.created_at).limit(1))
            if answer is not None:
                return _message_read(db, answer)

    selected = db.get(Material, payload.material_id) if payload.material_id else None
    if payload.material_id and (selected is None or selected.course_id != conversation.course_id or selected.deleted_at is not None):
        raise HTTPException(status_code=404, detail="所选资料不属于当前课程")
    user = ConversationMessage(
        conversation_id=conversation_id, role="user", content=payload.question.strip(),
        learning_goal=payload.learning_goal, status="completed", idempotency_key=payload.idempotency_key,
    )
    db.add(user)
    db.flush()
    history = [(message.role, message.content) for message in conversation.messages if message.id != user.id]
    course = ensure_course(db, conversation.course_id)
    try:
        result = run_answer(
            db,
            course_id=conversation.course_id,
            course_name=course.name,
            question=payload.question,
            material_id=payload.material_id,
            page_number=payload.page_number,
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
        return _message_read(db, assistant)
    except Exception as exc:
        db.rollback()
        failed = ConversationMessage(
            conversation_id=conversation_id, role="assistant",
            content="本次回答未完成，已保留失败状态；请稍后重试或查看课程检索片段。",
            learning_goal=payload.learning_goal, status="failed", failure_type=type(exc).__name__,
        )
        db.add(failed)
        db.commit()
        db.refresh(failed)
        return _message_read(db, failed)
