"""Shared persistence and loading for both conversation transports."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Conversation,
    ConversationMessage,
    Course,
    Material,
    MaterialPage,
    MessageEvidence,
    Note,
    Notebook,
    PageBlock,
    SourceRef,
    WebSource,
)
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_conversation, require_course

DEFAULT_CONVERSATION_TITLE = "新对话"


def normalize_conversation_scope(value: str | None) -> str:
    """Normalize current and legacy scope names at the application boundary."""
    if value in {"course", "global", "note"}:
        return value
    return "course"


def create_course_conversation(db: Session, *, course_id: str, title: str, scope: str,
                               note_id: str | None, note_title: str | None) -> Conversation:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise ApplicationError(404, "课程不存在")
    if scope == "note":
        notebook, error = resolve_legacy_note_target(db, note_id or "", course_id)
        if notebook is None:
            raise ApplicationError(409 if "同时指向" in (error or "") else 404,
                                   error or "锁定的笔记不存在或不属于当前课程")
        note_id, note_title = notebook.id, (note_title or notebook.title)[:300]
    conversation = Conversation(course_id=course_id, title=title, default_scope=scope,
        scope=scope, note_id=note_id if scope == "note" else None,
        note_title=note_title if scope == "note" else None)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def create_notebook_conversation(db: Session, notebook_id: str, title: str) -> Conversation:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    conversation = Conversation(course_id=None, notebook_id=notebook.id, title=title,
        default_scope="notebook", scope="notebook", note_title=notebook.title[:300])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def list_notebook_conversations(db: Session, notebook_id: str) -> list[Conversation]:
    if db.get(Notebook, notebook_id) is None:
        raise ApplicationError(404, "笔记不存在")
    return list(db.scalars(select(Conversation).where(
        Conversation.notebook_id == notebook_id, Conversation.scope == "notebook"
    ).order_by(Conversation.updated_at.desc())).all())


def rename_conversation(db: Session, conversation_id: str, title: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ApplicationError(404, "会话不存在")
    conversation.title = title
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation_id: str) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ApplicationError(404, "会话不存在")
    db.delete(conversation)
    db.commit()


def list_course_conversations(db: Session, course_id: str) -> list[Conversation]:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise ApplicationError(404, "课程不存在")
    conversations = list(db.scalars(select(Conversation).where(
        Conversation.course_id == course_id
    ).order_by(Conversation.updated_at.desc())).all())
    for conversation in conversations:
        if conversation.scope != "note" or not conversation.note_id:
            continue
        notebook, _ = resolve_legacy_note_target(db, conversation.note_id, course_id)
        if notebook is not None:
            conversation.note_id = notebook.id
            conversation.note_title = conversation.note_title or notebook.title
    return conversations


def list_conversation_messages(db: Session, conversation_id: str) -> tuple[Conversation, list[ConversationMessage]]:
    try:
        conversation = load_conversation(db, conversation_id)
    except ConversationUnavailable as exc:
        raise ApplicationError(404, exc.detail) from exc
    messages = list(db.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id
    ).options(
        selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.source_ref)
        .selectinload(SourceRef.page_block).selectinload(PageBlock.page),
        selectinload(ConversationMessage.evidence).selectinload(MessageEvidence.web_source),
    ).order_by(ConversationMessage.created_at)).all())
    return conversation, messages


def conversation_for_message(db: Session, conversation_id: str) -> Conversation:
    """Load and validate a conversation before an answer use case starts."""
    return require_conversation(db, conversation_id)


def idempotent_assistant_message(db: Session, conversation_id: str, key: str | None):
    if not key:
        return None
    existing = db.scalar(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.role == "user", ConversationMessage.idempotency_key == key,
    ))
    if existing is None:
        return None
    return db.scalar(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.role == "assistant",
        ConversationMessage.created_at >= existing.created_at,
    ).order_by(ConversationMessage.created_at).limit(1))


def notebook_for_conversation(db: Session, conversation: Conversation, context: dict):
    book = db.get(Notebook, conversation.notebook_id) if conversation.notebook_id else None
    if (book is None or book.deleted_at is not None or context.get("notebook_id") != book.id
            or context.get("course_id") != book.course_id
            or not isinstance(context.get("revision"), int)
            or context["revision"] != book.document_revision):
        raise ApplicationError(409, "请刷新并提供当前会话 Notebook 的最新正文版本")
    return book


def material_for_conversation(db: Session, conversation: Conversation, material_id: str | None):
    if not material_id:
        return None
    material = db.get(Material, material_id)
    from app.services.course_scope import material_in_course
    if material is None or material.deleted_at is not None or not material_in_course(
        db, material, conversation.course_id
    ):
        raise ApplicationError(404, "所选资料不属于当前课程")
    return material


def record_user_turn(db: Session, conversation: Conversation, *, question: str,
                     learning_goal: str | None, idempotency_key: str | None,
                     scope: str | None, note_id: str | None, note_title: str | None):
    history = [(item.role, item.content) for item in conversation.messages]
    is_first_turn = not any(item.role == "user" for item in conversation.messages)
    db.add(ConversationMessage(conversation_id=conversation.id, role="user",
        content=question.strip(), learning_goal=learning_goal, status="completed",
        idempotency_key=idempotency_key))
    if is_first_turn:
        new_scope = scope if scope in {"course", "global", "note"} else conversation.scope or "course"
        if new_scope in {"material", "page"}:
            new_scope = "course"
        conversation.default_scope = conversation.scope = new_scope
        conversation.note_id = note_id if new_scope == "note" else None
        conversation.note_title = note_title if new_scope == "note" else None
    if conversation.title.strip() == DEFAULT_CONVERSATION_TITLE:
        conversation.title = derive_conversation_title(question, conversation.scope, conversation.note_title)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApplicationError(409, "该问题已提交过，请勿重复发送") from exc
    return history


def record_failed_assistant_message(db: Session, conversation: Conversation, *, learning_goal: str | None,
                                    failure_type: str, notebook_scope: bool):
    db.rollback()
    fallback = ("本次 Notebook 答疑未完成，未发布未经核验的初稿。请稍后重试。" if notebook_scope
                else "本次回答未完成，已保留失败状态；请稍后重试或查看课程检索片段。")
    failed = ConversationMessage(conversation_id=conversation.id, role="assistant", content=fallback,
        learning_goal=learning_goal, status="failed", failure_type=failure_type)
    db.add(failed)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(failed)
    return failed


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


def resolve_legacy_note_target(db: Session, note_id: str, course_id: str) -> tuple[Notebook | None, str | None]:
    """Resolve old note_id data only when every matching legacy target is unambiguous."""
    candidates: list[Notebook] = []
    direct = db.get(Notebook, note_id)
    if direct is not None:
        candidates.append(direct)
    legacy_note = db.get(Note, note_id)
    if legacy_note is not None:
        mapped = db.get(Notebook, legacy_note.notebook_id) if legacy_note.notebook_id else None
        if mapped is None:
            return None, "旧笔记对应的 Notebook 已不存在，历史会话不可继续提问"
        candidates.append(mapped)
    if not candidates:
        return None, "旧笔记目标无法唯一解析，历史会话仅可阅读"
    distinct = {item.id: item for item in candidates}
    if len(distinct) != 1:
        return None, "旧笔记 ID 同时指向不同 Notebook，历史会话仅可阅读"
    notebook = next(iter(distinct.values()))
    if notebook.deleted_at is not None or notebook.course_id != course_id:
        return None, "旧笔记目标已删除或不属于原课程，历史会话仅可阅读"
    return notebook, None


def _hit_snippet(content: str, keyword: str, *, window: int = 60) -> str:
    index = content.lower().find(keyword.lower())
    if index < 0:
        return content[:window * 2] + ("…" if len(content) > window * 2 else "")
    start = max(0, index - window)
    end = min(len(content), index + len(keyword) + window)
    return f"{'…' if start else ''}{content[start:end]}{'…' if end < len(content) else ''}"


def search_course_messages(db: Session, course_id: str, query: str, *, limit: int = 20) -> list[dict]:
    require_course(db, course_id)
    keyword = query.strip()
    if not keyword:
        return []
    rows = db.execute(
        select(ConversationMessage, Conversation)
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .where(Conversation.course_id == course_id,
               ConversationMessage.content.icontains(keyword, autoescape=True))
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    ).all()
    return [{
        "conversation_id": conversation.id,
        "conversation_title": conversation.title,
        "message_id": message.id,
        "message_role": message.role,
        "snippet": _hit_snippet(message.content, keyword),
        "created_at": message.created_at,
    } for message, conversation in rows]


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
    if conversation.scope == "notebook":
        # Notebook deletion nulls the target FK but intentionally keeps the
        # transcript readable as historical content.
        if conversation.course_id is not None:
            raise ConversationUnavailable("Notebook 会话归属无效")
    else:
        course = db.get(Course, conversation.course_id) if conversation.course_id else None
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
    process: dict | None = None,
    suggestions: list[dict] | None = None,
) -> ConversationMessage:
    """Commit a complete assistant answer and its evidence in one transaction."""
    assistant = ConversationMessage(
        conversation_id=conversation.id, role="assistant", content=content,
        learning_goal=learning_goal, status="completed", model_version=model_version,
        process_json=json.dumps(process, ensure_ascii=False) if process else None,
        suggestions_json=json.dumps(suggestions, ensure_ascii=False) if suggestions else None,
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
                    document_block_ids_json=json.dumps(list(chunk.document_block_ids), ensure_ascii=False),
                    page_numbers_json=json.dumps(list(chunk.page_numbers), ensure_ascii=False),
                    parse_run_id=chunk.parse_run_id,
                    body_block_id=chunk.block_id,
                    notebook_revision=chunk.notebook_revision,
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
            source_scope = (
                WebSource.notebook_id == conversation.notebook_id
                if conversation.scope == "notebook" and conversation.notebook_id
                else WebSource.course_id == conversation.course_id
            )
            source = db.scalar(select(WebSource).where(source_scope, WebSource.url == item["url"]))
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
