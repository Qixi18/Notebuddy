from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.orchestrator import run_answer
from app.api.v1.shared import ensure_conversation, ensure_course
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
    ConversationTitleUpdate,
    MessageEvidenceRead,
)
from app.services.assistant_sources import sources_from_evidence
from app.services.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    derive_conversation_title,
    persist_assistant_message,
)

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


def _message_read(db: Session, message: ConversationMessage, conversation_title: str | None = None) -> ConversationMessageRead:
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
        conversation_title=conversation_title or DEFAULT_CONVERSATION_TITLE,
    )


_LEGACY_SCOPE = {"material": "course", "page": "course"}
_VALID_SCOPE = {"course", "global", "note"}


def _normalize_scope(value: str | None) -> str:
    """把旧词 material/page 与非法值都归一到 course / global / note。"""
    if not value:
        return "course"
    if value in _VALID_SCOPE:
        return value
    return _LEGACY_SCOPE.get(value, "course")


@router.post("/courses/{course_id}/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(course_id: str, payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    ensure_course(db, course_id)
    scope = _normalize_scope(payload.scope or payload.default_scope)
    # 只有锁定笔记的会话才带笔记快照；其余范围忽略，避免脏字段混进历史分组。
    note_id = payload.note_id if scope == "note" else None
    note_title = payload.note_title if scope == "note" else None
    conversation = Conversation(
        course_id=course_id,
        title=payload.title.strip(),
        default_scope=scope,
        scope=scope,
        note_id=note_id,
        note_title=note_title,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def rename_conversation(
    conversation_id: str, payload: ConversationTitleUpdate, db: Session = Depends(get_db),
) -> Conversation:
    """重命名会话：仅改标题。手动改名后，首条问题的自动命名不会再覆盖它。"""
    conversation = ensure_conversation(db, conversation_id)
    conversation.title = payload.title.strip()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> None:
    """删除整段会话。ORM 级联清空消息与证据（messages / evidence 均 delete-orphan，
    且 FK ondelete=CASCADE）；note_suggestions 不挂 conversation_id，无孤儿行。"""
    conversation = ensure_conversation(db, conversation_id)
    db.delete(conversation)
    db.commit()


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationRead])
def list_conversations(course_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    ensure_course(db, course_id)
    return list(db.scalars(select(Conversation).where(Conversation.course_id == course_id).order_by(Conversation.updated_at.desc())).all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageRead])
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[ConversationMessageRead]:
    conversation = ensure_conversation(db, conversation_id)
    messages = list(db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
        .options(
            selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.source_ref)
            .selectinload(SourceRef.page_block).selectinload(PageBlock.page),
            selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.web_source),
        ).order_by(ConversationMessage.created_at)
    ).all())
    return [_message_read(db, message, conversation.title) for message in messages]


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageRead, status_code=201)
def send_message(
    conversation_id: str,
    payload: ConversationMessageCreate,
    db: Session = Depends(get_db),
) -> ConversationMessageRead:
    conversation = ensure_conversation(db, conversation_id)
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
    history = [(message.role, message.content) for message in conversation.messages]
    is_first_turn = not any(message.role == "user" for message in conversation.messages)
    user = ConversationMessage(
        conversation_id=conversation_id, role="user", content=payload.question.strip(),
        learning_goal=payload.learning_goal, status="completed", idempotency_key=payload.idempotency_key,
    )
    db.add(user)
    # 范围是会话级属性：仅在本会话尚无任何用户消息时落库，把答疑页载入时自动建的
    # 空会话改写成用户实际选择的范围；此后的提问忽略 payload.scope。
    if is_first_turn:
        new_scope = _normalize_scope(payload.scope or conversation.scope)
        conversation.default_scope = new_scope
        conversation.scope = new_scope
        conversation.note_id = payload.note_id if new_scope == "note" else None
        conversation.note_title = payload.note_title if new_scope == "note" else None
    # 标题仍是默认值就用首条问题命名（同源复用：同一会话只命名一次）
    if conversation.title.strip() == DEFAULT_CONVERSATION_TITLE:
        conversation.title = derive_conversation_title(payload.question, conversation.scope, conversation.note_title)
    db.commit()
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
        return _message_read(db, assistant, conversation.title)
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
        db.refresh(failed)
        return _message_read(db, failed, conversation.title)
