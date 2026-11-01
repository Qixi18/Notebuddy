"""Notebook 路由共享的常量、小工具与导入。

拆分自 api/v1/notebook.py，供 notebook_routes/* 复用；不注册路由。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.models import (
    Asset,
    Course,
    Material,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookRevisionAsset,
)
from app.notes.assets import AssetUnavailable, assert_notebook_asset, storage_path
from app.notes.document import attachment_ids
from app.notes.notebook import default_notebook, notebook_outline
from app.schemas.notebook import NotebookOrderUpdate


def _ensure_document_image_ownership(db: Session, notebook_id: str, content: dict) -> None:
    stack = [content]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "image":
            attrs = node.get("attrs") or {}
            attachment_id = attrs.get("attachmentId")
            asset_id = attrs.get("assetId")
            if attachment_id:
                attachment = db.get(NotebookAttachment, attachment_id)
                if attachment is None or attachment.notebook_id != notebook_id:
                    raise HTTPException(422, "图片附件不属于当前笔记")
                if attachment.asset_id:
                    try:
                        assert_notebook_asset(db, attachment.asset_id, notebook_id)
                    except AssetUnavailable as exc:
                        raise HTTPException(422, "图片附件资源不属于当前笔记或不可用") from exc
            elif asset_id:
                try:
                    assert_notebook_asset(db, asset_id, notebook_id)
                except AssetUnavailable as exc:
                    raise HTTPException(422, "图片资源不属于当前笔记或不可用") from exc
        stack.extend(node.get("content") or [])

def _restore_document_image_ownership(
    db: Session, notebook_id: str, content: dict, source_revision_id: str,
) -> None:
    """Reactivate only assets pinned by the exact revision being restored."""
    for reference_id in attachment_ids(content):
        attachment = db.get(NotebookAttachment, reference_id)
        if attachment is not None and attachment.notebook_id != notebook_id:
            raise HTTPException(422, "历史版本包含其他笔记的图片附件")
        asset_id = attachment.asset_id if attachment is not None and attachment.asset_id else reference_id
        asset = db.get(Asset, asset_id)
        if asset is None:
            # Legacy attachments that were intentionally left unmapped remain
            # readable through the compatibility route and are not Asset IDs.
            if attachment is not None:
                continue
            raise HTTPException(422, "历史版本引用的资源不存在")
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.is_owner.is_(True),
        ))
        if owner is None:
            raise HTTPException(422, "历史版本引用的资源不属于当前笔记")
        if owner.detached_at is not None:
            pinned = db.scalar(select(NotebookRevisionAsset.id).where(
                NotebookRevisionAsset.revision_id == source_revision_id,
                NotebookRevisionAsset.notebook_id == notebook_id,
                NotebookRevisionAsset.owner_link_id == owner.id,
                NotebookRevisionAsset.asset_id == asset_id,
            ))
            if pinned is None:
                raise HTTPException(422, "历史版本没有权限恢复已解除的图片资源")
        if asset.state != "ready":
            raise HTTPException(409, "历史版本图片当前不可用，无法恢复")
        try:
            storage_path(asset)
        except AssetUnavailable as exc:
            raise HTTPException(409, "历史版本图片文件缺失，无法恢复") from exc
        owner.detached_at = None

def _cover_url(book: Notebook) -> str | None:
    return f"/api/v1/notebooks/{book.id}/cover" if book.cover_filename else None

def _summary(book: Notebook) -> dict:
    return {"id": book.id, "course_id": book.course_id, "title": book.title,
            "tree_slot": book.tree_slot, "display_order": book.display_order,
            "order_revision": book.order_revision, "is_default": book.is_default,
            "created_at": book.created_at, "updated_at": book.updated_at,
            "deleted_at": book.deleted_at,
            "cover_url": _cover_url(book)}

def ensure_notebook(db: Session, course_id: str, notebook_id: str) -> Notebook:
    ensure_course(db, course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id != course_id or book.deleted_at is not None:
        raise HTTPException(404, "该课程中的笔记本不存在")
    return book

def reorder(db: Session, course_id: str, book: Notebook, payload: NotebookOrderUpdate):
    result = db.execute(update(Notebook).where(
        Notebook.id == book.id, Notebook.order_revision == payload.expected_order_revision
    ).values(order_revision=Notebook.order_revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "章节已变化，请刷新目录后重新排序")
    materials = db.scalars(select(Material).where(Material.notebook_id == book.id,
                                                 Material.deleted_at.is_(None))).all()
    ids = payload.material_ids
    if len(set(ids)) != len(ids) or set(ids) != {m.id for m in materials}:
        db.rollback()
        raise HTTPException(422, "顺序必须包含当前笔记本全部章节，且不得重复")
    positions = {material_id: i for i, material_id in enumerate(ids)}
    for material in materials:
        material.chapter_order = positions[material.id]
    db.commit()
    db.refresh(book)
    return notebook_outline(db, db.get(Course, course_id), book)

def legacy_book(db: Session, course: Course) -> Notebook:
    book = default_notebook(db, course, create=False)
    if book is None:
        raise HTTPException(404, "此课程尚无笔记本，请先新建笔记本")
    return book
