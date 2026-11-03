"""Application use cases for explicit Notebook and Forest relations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Notebook, NotebookRelation
from app.forest.service import notebook_relation_display, relation_anchor_fingerprint
from app.services.errors import ApplicationError


def _anchor_pair(source: Notebook, target: Notebook, source_block_id: str | None,
                 target_block_id: str | None) -> tuple[str | None, str | None]:
    fingerprints = (
        relation_anchor_fingerprint(source, source_block_id),
        relation_anchor_fingerprint(target, target_block_id),
    )
    if any(block_id is not None and fingerprint is None for block_id, fingerprint in zip(
        (source_block_id, target_block_id), fingerprints, strict=True,
    )):
        raise ApplicationError(422, "关联小节不存在于所选笔记的当前正文，请重新选择")
    return fingerprints


def list_notebook_relations(db: Session, notebook_id: str) -> list[dict]:
    """Return outgoing and incoming explicit relations for an active Notebook."""
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    # Resolve the related Notebook and retain the response shape expected by
    # the existing API clients.
    relations = []
    for direction, relation, related in (
        ("outgoing", relation, db.get(Notebook, relation.target_notebook_id))
        for relation in db.scalars(select(NotebookRelation).where(
            NotebookRelation.source_notebook_id == notebook_id,
        )).all()
    ):
        if related is not None:
            relations.append(_relation_list_item(relation, related, direction))
    for direction, relation, related in (
        ("incoming", relation, db.get(Notebook, relation.source_notebook_id))
        for relation in db.scalars(select(NotebookRelation).where(
            NotebookRelation.target_notebook_id == notebook_id,
        )).all()
    ):
        if related is not None:
            relations.append(_relation_list_item(relation, related, direction))
    return sorted(relations, key=lambda relation: (relation["created_at"], relation["id"]), reverse=True)


def _relation_list_item(
    relation: NotebookRelation, related: Notebook, direction: str,
) -> dict:
    return {
        "id": relation.id,
        "source_notebook_id": relation.source_notebook_id,
        "target_notebook_id": relation.target_notebook_id,
        "related_notebook_id": (
            relation.target_notebook_id if direction == "outgoing"
            else relation.source_notebook_id
        ),
        "related_notebook_title": related.title,
        "direction": direction,
        "relation_type": relation.relation_type,
        "description": relation.description,
        "created_at": relation.created_at,
    }


def create_notebook_relation(db: Session, *, source_id: str, target_id: str,
                             relation_type: str, description: str | None) -> dict:
    source, target = db.get(Notebook, source_id), db.get(Notebook, target_id)
    if source is None or source.deleted_at is not None:
        raise ApplicationError(404, "源笔记不存在")
    if target is None or target.deleted_at is not None:
        raise ApplicationError(404, "目标笔记不存在")
    if source.id == target.id:
        raise ApplicationError(422, "笔记不能关联到自身")
    relation = NotebookRelation(
        source_notebook_id=source.id, target_notebook_id=target.id,
        relation_type=relation_type.strip(), description=description,
    )
    return _save_relation(db, relation, {
        "id": relation.id, "source_notebook_id": source.id,
        "target_notebook_id": target.id, "related_notebook_id": target.id,
        "related_notebook_title": target.title, "direction": "outgoing",
    })


def create_forest_relation(db: Session, *, source_id: str, target_id: str,
                           relation_type: str, reason: str,
                           source_block_id: str | None, target_block_id: str | None) -> dict:
    source, target = db.get(Notebook, source_id), db.get(Notebook, target_id)
    for notebook in (source, target):
        if notebook is None or notebook.deleted_at is not None or notebook.course_id is None:
            raise ApplicationError(404, "关系引用的笔记不存在或尚未归入课程")
    assert source is not None and target is not None
    if source.id == target.id or source.course_id == target.course_id:
        raise ApplicationError(422, "跨课关系必须引用不同课程中的两本笔记")
    fingerprints = _anchor_pair(source, target, source_block_id, target_block_id)
    relation = NotebookRelation(
        source_notebook_id=source.id, target_notebook_id=target.id,
        relation_type=relation_type, description=reason,
        source_block_id=source_block_id, target_block_id=target_block_id,
        source_fingerprint=fingerprints[0], target_fingerprint=fingerprints[1],
    )
    _save_relation(db, relation)
    display = notebook_relation_display(db, relation)
    if display is None:
        raise ApplicationError(409, "关系创建后无法展示，请检查课程归属")
    return display


def _save_relation(db: Session, relation: NotebookRelation, basic: dict | None = None) -> dict:
    db.add(relation)
    try:
        # Materialize ORM defaults (notably the generated ID) before building
        # the response payload, while keeping insert and commit in one txn.
        db.flush()
        if basic is not None:
            basic["id"] = relation.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = "该关系已存在" if basic else "这两本笔记的同类型关系已存在"
        raise ApplicationError(409, message) from exc
    db.refresh(relation)
    return {**(basic or {}), "relation_type": relation.relation_type,
            "description": relation.description, "created_at": relation.created_at,
            **({"origin": relation.origin} if basic else {})}


def delete_notebook_relation(db: Session, relation_id: str, *, notebook_id: str | None = None) -> None:
    relation = db.get(NotebookRelation, relation_id)
    if relation is None or (notebook_id and notebook_id not in (
        relation.source_notebook_id, relation.target_notebook_id,
    )):
        raise ApplicationError(404, "笔记关系不存在" if notebook_id else "关系不存在")
    from app.forest.suppressions import suppress

    suppress(db, relation)
    db.delete(relation)
    db.commit()


def refresh_forest_relation(db: Session, relation_id: str) -> dict:
    relation = db.get(NotebookRelation, relation_id)
    if relation is None or notebook_relation_display(db, relation) is None:
        raise ApplicationError(404, "关系不存在或笔记已不可用")
    source = db.get(Notebook, relation.source_notebook_id)
    target = db.get(Notebook, relation.target_notebook_id)
    fingerprints = _anchor_pair(source, target, relation.source_block_id, relation.target_block_id)
    relation.source_fingerprint, relation.target_fingerprint = fingerprints
    db.commit()
    return notebook_relation_display(db, relation)
