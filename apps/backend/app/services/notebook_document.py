"""Notebook document use cases.

HTTP routes resolve the Notebook and translate request/response models. This
module owns document compatibility rules, image ownership, revision handling,
history restore permissions, and transaction boundaries.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookRevisionAsset,
)
from app.notes.assets import AssetUnavailable, assert_notebook_asset, storage_path
from app.notes.document import (
    DocumentValidationError,
    attachment_ids,
    legacy_blocks_to_document,
    load_document,
    normalize_document,
    validate_document,
)
from app.notes.history import get_snapshot
from app.notes.store import DocumentConflict, write_document
from app.schemas.notebook import NotebookDocumentUpdate
from app.services.errors import ApplicationError


def validate_document_image_ownership(
    db: Session, notebook_id: str, content: dict,
) -> None:
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
                    raise ApplicationError(422, "图片附件不属于当前笔记")
                if attachment.asset_id:
                    try:
                        assert_notebook_asset(db, attachment.asset_id, notebook_id)
                    except AssetUnavailable as exc:
                        raise ApplicationError(422, "图片附件资源不属于当前笔记或不可用") from exc
            elif asset_id:
                try:
                    assert_notebook_asset(db, asset_id, notebook_id)
                except AssetUnavailable as exc:
                    raise ApplicationError(422, "图片资源不属于当前笔记或不可用") from exc
        stack.extend(node.get("content") or [])


def restore_document_image_ownership(
    db: Session, notebook_id: str, content: dict, source_revision_id: str,
) -> None:
    """Reactivate only assets pinned by the exact revision being restored."""
    for reference_id in attachment_ids(content):
        attachment = db.get(NotebookAttachment, reference_id)
        if attachment is not None and attachment.notebook_id != notebook_id:
            raise ApplicationError(422, "历史版本包含其他笔记的图片附件")
        asset_id = attachment.asset_id if attachment is not None and attachment.asset_id else reference_id
        asset = db.get(Asset, asset_id)
        if asset is None:
            if attachment is not None:
                continue
            raise ApplicationError(422, "历史版本引用的资源不存在")
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.is_owner.is_(True),
        ))
        if owner is None:
            raise ApplicationError(422, "历史版本引用的资源不属于当前笔记")
        if owner.detached_at is not None:
            pinned = db.scalar(select(NotebookRevisionAsset.id).where(
                NotebookRevisionAsset.revision_id == source_revision_id,
                NotebookRevisionAsset.notebook_id == notebook_id,
                NotebookRevisionAsset.owner_link_id == owner.id,
                NotebookRevisionAsset.asset_id == asset_id,
            ))
            if pinned is None:
                raise ApplicationError(422, "历史版本没有权限恢复已解除的图片资源")
        if asset.state != "ready":
            raise ApplicationError(409, "历史版本图片当前不可用，无法恢复")
        try:
            storage_path(asset)
        except AssetUnavailable as exc:
            raise ApplicationError(409, "历史版本图片文件缺失，无法恢复") from exc
        owner.detached_at = None


def save_notebook_document(
    db: Session,
    notebook: Notebook,
    payload: NotebookDocumentUpdate,
    *,
    refresh_relations: bool,
) -> tuple[int, dict]:
    """Validate and atomically save the editable Notebook body."""
    if payload.blocks is not None and not load_document(notebook.document_json).legacy:
        raise ApplicationError(409, "笔记已使用新版编辑器，请刷新页面后继续编辑")
    try:
        if payload.content is not None:
            content = payload.content
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise ApplicationError(422, "正文块编号不能重复")
            content = legacy_blocks_to_document(blocks)
        normalized = validate_document(normalize_document(content))
        validate_document_image_ownership(db, notebook.id, normalized)
        revision, stored = write_document(
            db, notebook, normalized,
            expected_revision=payload.expected_revision,
            origin="autosave",
            legacy_compatible=payload.blocks is not None,
            refresh_relations=refresh_relations,
        )
        db.commit()
        return revision, stored
    except DocumentConflict as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    except DocumentValidationError as exc:
        db.rollback()
        raise ApplicationError(422, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def restore_notebook_document(
    db: Session,
    notebook: Notebook,
    source_revision: int,
    expected_revision: int,
    *,
    refresh_relations: bool,
) -> tuple[int, dict]:
    snapshot = get_snapshot(db, notebook.id, source_revision)
    if snapshot is None:
        raise ApplicationError(404, "历史版本不存在")
    content = load_document(snapshot.document_json).content
    try:
        restore_document_image_ownership(db, notebook.id, content, snapshot.id)
        revision, stored = write_document(
            db, notebook, content, expected_revision=expected_revision,
            origin="restore", refresh_relations=refresh_relations,
        )
        db.commit()
        return revision, stored
    except DocumentConflict as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    except DocumentValidationError as exc:
        db.rollback()
        raise ApplicationError(422, f"历史版本内容已失效：{exc}") from exc
    except Exception:
        db.rollback()
        raise
