"""Shared persistence and loading for both conversation transports."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.shared import ensure_course
from app.db.models import (
    Conversation,
    ConversationMessage,
    MessageEvidence,
    PageBlock,
    SourceRef,
    WebSource,
)


def load_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).options(
            selectinload(Conversation.messages)
            .selectinload(ConversationMessage.evidence)
            .selectinload(MessageEvidence.source_ref)
            .selectinload(SourceRef.page_block)
            .selectinload(PageBlock.page),
            selectinload(Conversation.messages)
            .selectinload(ConversationMessage.evidence)
            .selectinload(MessageEvidence.web_source),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    ensure_course(db, conversation.course_id)
    return conversation


def persist_assistant_message(
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
    """Commit a complete assistant answer and its evidence in one transaction."""
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
