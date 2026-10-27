"""Shared persistence and loading for both conversation transports."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Conversation,
    ConversationMessage,
    Course,
    Material,
    MaterialPage,
    MessageEvidence,
    PageBlock,
    SourceRef,
    WebSource,
)

DEFAULT_CONVERSATION_TITLE = "新对话"


def derive_conversation_title(question: str, scope: str | None, note_title: str | None) -> str:
    """用首条用户问题生成会话标题，替代默认的「新对话」。

    全局可查 / 锁定笔记加前缀，便于历史列表区分同题不同范围；
    整门课程最常见，不加前缀。上限沿用 Conversation.title 的 300。
    """
    text = " ".join(question.split())
    limit = 18
    if len(text) > limit:
        text = text[:limit] + "…"
    if scope == "global":
        prefix = "全局可查 · "
    elif scope == "note":
        prefix = f"{note_title or '锁定笔记'} · "
    else:
        prefix = ""
    return (prefix + text)[:300]


class ConversationUnavailable(Exception):
    """A conversation or its course is unavailable to the caller."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


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
        raise ConversationUnavailable("会话不存在")
    course = db.get(Course, conversation.course_id)
    if course is None or course.deleted_at is not None:
        raise ConversationUnavailable("课程不存在")
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
            if getattr(chunk, "kind", "legacy") in {"document", "notebook"}:
                db.add(MessageEvidence(
                    message_id=assistant.id,
                    notebook_id=chunk.notebook_id,
                    document_block_id=chunk.document_block_id,
                    parse_run_id=chunk.parse_run_id,
                    body_block_id=chunk.block_id,
                    source_title=chunk.lecture_title,
                    location_label=chunk.location_label,
                    snippet=chunk.text[:600],
                    claim_key=claim_key,
                    evidence_type=str(claim.get("evidence_type") or (
                        "course_direct" if chunk.direct_support else "course_related"
                    )),
                    support_level="direct" if chunk.direct_support else "related",
                ))
                linked_source = True
                continue
            source_ref = None
            for criterion in (
                (SourceRef.id == chunk.source_ref_id) if chunk.source_ref_id else None,
                (SourceRef.page_block_id == chunk.page_block_id) if chunk.page_block_id else None,
            ):
                if criterion is None:
                    continue
                source_ref = db.scalar(
                    select(SourceRef)
                    .join(PageBlock).join(MaterialPage).join(Material)
                    .where(
                        SourceRef.status == "active",
                        Material.course_id == conversation.course_id,
                        Material.deleted_at.is_(None), criterion,
                    )
                )
                if source_ref is not None:
                    break
            if source_ref is None:
                continue
            db.add(MessageEvidence(
                message_id=assistant.id,
                source_ref_id=source_ref.id,
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
                evidence_type="general_explanation", support_level="unverified",
            ))
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(assistant)
    return assistant
