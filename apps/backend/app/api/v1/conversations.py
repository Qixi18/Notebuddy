from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Conversation, ConversationMessage
from app.schemas.api import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationMessageHit,
    ConversationMessageRead,
    ConversationRead,
    ConversationTitleUpdate,
    MessageEvidenceRead,
)
from app.services.assistant_execution import (
    send_conversation_message,
)
from app.services.assistant_sources import sources_from_evidence
from app.services.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    list_conversation_messages,
    normalize_conversation_scope,
    search_course_messages,
)
from app.services.conversations import (
    create_course_conversation as create_course_conversation_use_case,
)
from app.services.conversations import (
    create_notebook_conversation as create_notebook_conversation_use_case,
)
from app.services.conversations import (
    delete_conversation as delete_conversation_use_case,
)
from app.services.conversations import (
    list_course_conversations as list_course_conversations_use_case,
)
from app.services.conversations import (
    list_notebook_conversations as list_notebook_conversations_use_case,
)
from app.services.conversations import (
    rename_conversation as rename_conversation_use_case,
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
        else:
            snippet = item.snippet
            location_label = item.location_label
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
        process={key: value for key, value in (message.process or {}).items() if key != "verification"} or None,
        verification=(message.process or {}).get("verification"),
        suggestions=message.suggestions,
        conversation_title=conversation_title or DEFAULT_CONVERSATION_TITLE,
    )


@router.post("/courses/{course_id}/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(course_id: str, payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    scope = normalize_conversation_scope(payload.scope or payload.default_scope)
    # 只有锁定笔记的会话才带笔记快照；其余范围忽略，避免脏字段混进历史分组。
    note_id = payload.note_id if scope == "note" else None
    note_title = payload.note_title if scope == "note" else None
    return create_course_conversation_use_case(db, course_id=course_id, title=payload.title.strip(),
        scope=scope, note_id=note_id, note_title=note_title)


@router.post("/notebooks/{notebook_id}/conversations", response_model=ConversationRead, status_code=201)
def create_notebook_conversation(
    notebook_id: str, payload: ConversationCreate, db: Session = Depends(get_db),
) -> Conversation:
    """Create a transcript owned by one Notebook, independent of its course binding."""
    return create_notebook_conversation_use_case(db, notebook_id, payload.title.strip())


@router.get("/notebooks/{notebook_id}/conversations", response_model=list[ConversationRead])
def list_notebook_conversations(notebook_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    return list_notebook_conversations_use_case(db, notebook_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def rename_conversation(
    conversation_id: str, payload: ConversationTitleUpdate, db: Session = Depends(get_db),
) -> Conversation:
    """重命名会话：仅改标题。手动改名后，首条问题的自动命名不会再覆盖它。"""
    return rename_conversation_use_case(db, conversation_id, payload.title.strip())


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> None:
    """删除整段会话。ORM 级联清空消息与证据（messages / evidence 均 delete-orphan，
    且 FK ondelete=CASCADE）；note_suggestions 不挂 conversation_id，无孤儿行。"""
    delete_conversation_use_case(db, conversation_id)


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationRead])
def list_conversations(course_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    return list_course_conversations_use_case(db, course_id)


@router.get("/courses/{course_id}/conversations/search", response_model=list[ConversationMessageHit])
def search_course_conversations(
    course_id: str, q: str = Query(default="", max_length=120), db: Session = Depends(get_db)
) -> list[dict]:
    """课程内会话消息全文搜索（P6）：提问与回答都参与匹配，返回消息级命中片段。"""
    return search_course_messages(db, course_id, q)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageRead])
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[ConversationMessageRead]:
    conversation, messages = list_conversation_messages(db, conversation_id)
    return [_message_read(db, message, conversation.title) for message in messages]


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageRead, status_code=201)
def send_message(
    conversation_id: str,
    payload: ConversationMessageCreate,
    db: Session = Depends(get_db),
) -> ConversationMessageRead:
    conversation, assistant = send_conversation_message(
        db, conversation_id, question=payload.question,
        learning_goal=payload.learning_goal,
        idempotency_key=payload.idempotency_key, allow_web=payload.allow_web,
        notebook_context=payload.notebook_context,
        material_id=payload.material_id, page_number=payload.page_number,
        scope=payload.scope, note_id=payload.note_id, note_title=payload.note_title,
        teacher_persona=payload.teacher_persona,
    )
    return _message_read(db, assistant, conversation.title)
