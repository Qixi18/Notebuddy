"""Notebook edit suggestion review use cases."""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Notebook, NotebookEditSuggestion, utc_now
from app.notes.document import (
    DocumentValidationError,
    document_to_blocks,
    load_document,
)
from app.notes.edits import EditRejected, apply_edits
from app.notes.store import DocumentConflict, write_document
from app.services.errors import ApplicationError
from app.services.notebook_document import validate_document_image_ownership


@dataclass(frozen=True)
class SuggestionReview:
    decision: str
    expected_revision: int
    selected_operation_indices: list[int] | None = None


def list_notebook_edit_suggestions(
    db: Session, notebook_id: str, status: str | None = "pending",
) -> list[dict]:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    query = select(NotebookEditSuggestion).where(
        NotebookEditSuggestion.notebook_id == notebook_id,
    )
    if status:
        query = query.where(NotebookEditSuggestion.status == status)
    rows = db.scalars(query.order_by(
        NotebookEditSuggestion.created_at.desc()).limit(50)).all()
    return [_suggestion_payload(row) for row in rows]


def list_course_edit_suggestions(
    db: Session, course_id: str, status: str | None = "pending",
) -> list[dict]:
    rows = db.execute(
        select(NotebookEditSuggestion, Notebook.title)
        .join(Notebook, Notebook.id == NotebookEditSuggestion.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
               *([NotebookEditSuggestion.status == status] if status else []))
        .order_by(NotebookEditSuggestion.created_at.desc())
        .limit(200)
    ).all()
    return [_suggestion_payload(row, notebook_title=title) for row, title in rows]


def _suggestion_payload(
    row: NotebookEditSuggestion, *, notebook_title: str | None = None,
) -> dict:
    try:
        operations = json.loads(row.ops_json)
        proposed = load_document(row.proposed_document_json)
        proposed_content = proposed.content if proposed.warning is None else None
    except (TypeError, ValueError):
        operations, proposed_content = [], None
    payload = {
        "id": row.id,
        "notebook_id": row.notebook_id,
        "base_revision": row.base_revision,
        "rationale": row.rationale,
        "operations": operations if isinstance(operations, list) else [],
        "proposed_content": proposed_content,
        "status": row.status,
        "created_at": row.created_at,
        "reviewed_at": row.reviewed_at,
    }
    if notebook_title is not None:
        payload["notebook_title"] = notebook_title
    return payload


def review_edit_suggestion(
    db: Session, notebook_id: str, suggestion_id: str,
    payload: SuggestionReview,
) -> dict:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    suggestion = db.get(NotebookEditSuggestion, suggestion_id)
    if suggestion is None or suggestion.notebook_id != notebook_id:
        raise ApplicationError(404, "修改建议不存在")
    if suggestion.status != "pending":
        raise ApplicationError(409, "该建议已处理")
    now = utc_now()
    if payload.decision == "reject":
        changed = db.execute(update(NotebookEditSuggestion).where(
            NotebookEditSuggestion.id == suggestion_id,
            NotebookEditSuggestion.notebook_id == notebook_id,
            NotebookEditSuggestion.status == "pending",
        ).values(status="rejected", reviewed_at=now))
        if changed.rowcount != 1:
            db.rollback()
            raise ApplicationError(409, "该建议已处理")
        db.commit()
        return _document_response(book.document_json, book.document_revision, book.updated_at)
    if book.document_revision != suggestion.base_revision:
        suggestion.status = "stale"
        suggestion.reviewed_at = now
        db.commit()
        raise ApplicationError(409, "笔记正文已变化，该建议已失效；请重新生成修改建议")
    if payload.expected_revision != book.document_revision:
        raise ApplicationError(409, "笔记正文版本已变化，请刷新后重试")
    try:
        operations = json.loads(suggestion.ops_json)
        if not isinstance(operations, list) or not operations:
            raise ValueError("修改建议缺少有效操作")
        selected = payload.selected_operation_indices
        if selected is not None:
            if (not selected or len(set(selected)) != len(selected)
                    or any(index < 0 or index >= len(operations) for index in selected)):
                raise ValueError("所选修改操作无效")
            operations = [operations[index] for index in selected]
        proposed = load_document(suggestion.proposed_document_json) if selected is None else None
        proposed_content = proposed.content if proposed is not None else apply_edits(
            load_document(book.document_json).content, operations,
        )
    except (TypeError, ValueError, EditRejected) as exc:
        raise ApplicationError(422, f"修改建议内容无效：{exc}") from exc
    if proposed is not None and proposed.warning:
        raise ApplicationError(422, proposed.warning)
    validate_document_image_ownership(db, notebook_id, proposed_content)
    changed = db.execute(update(NotebookEditSuggestion).where(
        NotebookEditSuggestion.id == suggestion_id,
        NotebookEditSuggestion.notebook_id == notebook_id,
        NotebookEditSuggestion.status == "pending",
    ).values(status="applying"))
    if changed.rowcount != 1:
        db.rollback()
        raise ApplicationError(409, "该建议已处理")
    try:
        next_revision, content = write_document(
            db, book, proposed_content, expected_revision=payload.expected_revision,
            origin="ai_suggestion", refresh_relations=True,
        )
    except DocumentConflict as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    suggestion.status = "accepted" if payload.selected_operation_indices is None else "partially_accepted"
    suggestion.reviewed_at = now
    db.commit()
    return _document_response(content, next_revision, book.updated_at)


def apply_course_edit_suggestions(
    db: Session, course_id: str, suggestion_ids: list[str],
) -> dict:
    if len(set(suggestion_ids)) != len(suggestion_ids):
        raise ApplicationError(422, "修改建议编号不能重复")
    rows = db.execute(
        select(NotebookEditSuggestion, Notebook)
        .join(Notebook, Notebook.id == NotebookEditSuggestion.notebook_id)
        .where(NotebookEditSuggestion.id.in_(suggestion_ids),
               Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
        .order_by(NotebookEditSuggestion.created_at, NotebookEditSuggestion.id)
    ).all()
    if len(rows) != len(suggestion_ids):
        raise ApplicationError(404, "部分修改建议不存在或不属于当前课程")
    grouped: dict[str, tuple[Notebook, list[NotebookEditSuggestion]]] = {}
    for suggestion, book in rows:
        grouped.setdefault(book.id, (book, []))[1].append(suggestion)
    now = utc_now()
    try:
        stale = [suggestion for _, suggestions in grouped.values() for suggestion in suggestions
                 if suggestion.status != "pending"]
        if stale:
            raise ApplicationError(409, "部分修改建议已处理，请刷新列表")
        mismatched = [suggestion for book, suggestions in grouped.values() for suggestion in suggestions
                      if suggestion.base_revision != book.document_revision]
        if mismatched:
            for suggestion in mismatched:
                suggestion.status = "stale"
                suggestion.reviewed_at = now
            db.commit()
            raise ApplicationError(409, "部分笔记正文已变化，对应建议已失效；请刷新后重新生成")
        claimed = db.execute(update(NotebookEditSuggestion).where(
            NotebookEditSuggestion.id.in_(suggestion_ids),
            NotebookEditSuggestion.status == "pending",
        ).values(status="applying"))
        if claimed.rowcount != len(suggestion_ids):
            db.rollback()
            raise ApplicationError(409, "部分修改建议刚被其他请求处理，请刷新列表")
        results = []
        for book, suggestions in grouped.values():
            stored = load_document(book.document_json)
            if stored.warning:
                raise ValueError(f"Notebook《{book.title}》正文无法解析，不能应用修改建议")
            content = stored.content
            for suggestion in suggestions:
                operations = json.loads(suggestion.ops_json)
                if not isinstance(operations, list) or not operations:
                    raise ValueError("修改建议缺少有效操作")
                content = apply_edits(content, operations)
            validate_document_image_ownership(db, book.id, content)
            next_revision, _ = write_document(
                db, book, content, expected_revision=book.document_revision,
                origin="ai_suggestion", refresh_relations=True,
            )
            for suggestion in suggestions:
                suggestion.status = "accepted"
                suggestion.reviewed_at = now
            results.append({"notebook_id": book.id, "revision": next_revision,
                            "suggestion_count": len(suggestions)})
        from app.forest.notebook_relations import enqueue_notebook_relations

        enqueue_notebook_relations(db, course_id)
        db.commit()
        return {"updated": sum(item["suggestion_count"] for item in results), "notebooks": results}
    except ApplicationError:
        raise
    except (TypeError, ValueError, EditRejected, DocumentValidationError) as exc:
        db.rollback()
        raise ApplicationError(422, f"修改建议无法合并：{exc}") from exc
    except DocumentConflict as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc


def _document_response(content_json: str, revision: int, updated_at) -> dict:
    content = load_document(content_json).content if isinstance(content_json, str) else content_json
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": revision, "updated_at": updated_at}
