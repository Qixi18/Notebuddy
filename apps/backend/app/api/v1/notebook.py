import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Asset,
    AssetProcessingJob,
    Course,
    Material,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookCoverAsset,
    NotebookEditSuggestion,
    NotebookGenerationJob,
    NotebookReadingPosition,
    NotebookRelation,
    NotebookRevisionAsset,
    NotebookSection,
    ProcessingJob,
    utc_now,
)
from app.notes.assets import (
    AssetUnavailable,
    assert_notebook_asset,
    has_live_asset_references,
    storage_path,
)
from app.notes.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentRejected,
    attachment_path,
    public_url,
    store_attachment,
)
from app.notes.document import (
    DocumentValidationError,
    attachment_ids,
    document_to_blocks,
    legacy_blocks_to_document,
    load_document,
    normalize_document,
)
from app.notes.edits import EditRejected, apply_edits
from app.notes.history import get_snapshot, list_snapshots
from app.notes.index import sections_for_notebook
from app.notes.notebook import default_notebook, list_course_notebooks, notebook_outline
from app.notes.store import DocumentConflict, block_source_payload, write_document
from app.schemas.notebook import (
    BlockSourceRead,
    NotebookAttachmentRead,
    NotebookBindRequest,
    NotebookBulkManageRequest,
    NotebookDocumentRead,
    NotebookDocumentUpdate,
    NotebookEditSuggestionRead,
    NotebookEditSuggestionReview,
    NotebookMoveRequest,
    NotebookOrderUpdate,
    NotebookRead,
    NotebookRelationCreate,
    NotebookRelationRead,
    NotebookRestoreDeletedRequest,
    NotebookRestoreRequest,
    NotebookRevisionRead,
    NotebookRevisionSummary,
    NotebookSummary,
    NotebookTitleUpdate,
    ReadingPositionRead,
    ReadingPositionUpdate,
    UnboundNotebookSummary,
)

router = APIRouter()


@router.post("/notebooks/bulk-manage")
def bulk_manage_notebooks(payload: NotebookBulkManageRequest, db: Session = Depends(get_db)):
    books = list(db.scalars(select(Notebook).where(
        Notebook.id.in_(payload.notebook_ids), Notebook.deleted_at.is_(None)
    )).all())
    if len(books) != len(payload.notebook_ids):
        raise HTTPException(404, "部分笔记不存在或已在回收站，请刷新列表后重试")

    if payload.action == "delete":
        active_jobs = db.scalar(select(func.count()).select_from(ProcessingJob).join(
            Material, ProcessingJob.material_id == Material.id).where(
            Material.notebook_id.in_(payload.notebook_ids),
            ProcessingJob.status.in_(["pending", "processing"]))) or 0
        active_jobs += db.scalar(select(func.count()).select_from(AssetProcessingJob).join(
            Material, Material.asset_id == AssetProcessingJob.asset_id).where(
            Material.notebook_id.in_(payload.notebook_ids),
            AssetProcessingJob.status.in_(["pending", "processing"]))) or 0
        active_jobs += db.scalar(select(func.count()).select_from(NotebookGenerationJob).where(
            NotebookGenerationJob.notebook_id.in_(payload.notebook_ids),
            NotebookGenerationJob.status.in_(["pending", "processing"]))) or 0
        if active_jobs:
            raise HTTPException(409, "所选笔记中仍有资料处理任务；完成或取消后再删除")
        from datetime import UTC, datetime

        from app.services.deletion import _checkpoint
        _checkpoint()
        deleted_at = datetime.now(UTC)
        for book in books:
            book.deleted_at = deleted_at
            book.is_default = False
        changed_courses = {book.course_id for book in books if book.course_id}
        for course_id in changed_courses:
            remaining = list(db.scalars(select(Notebook).where(
                Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
                Notebook.id.not_in(payload.notebook_ids),
            ).order_by(Notebook.display_order, Notebook.id)).all())
            if remaining and not any(item.is_default for item in remaining):
                remaining[0].is_default = True
            db.execute(update(Course).where(Course.id == course_id).values(
                notebook_order_revision=Course.notebook_order_revision + 1))
        db.commit()
        return {"action": "delete", "affected": len(books)}

    target = ensure_course(db, payload.course_id) if payload.course_id else None
    target_id = target.id if target else None
    moving = [book for book in books if book.course_id != target_id]
    if not moving:
        return {"action": "move", "affected": 0}

    source_courses = {book.course_id for book in moving if book.course_id}
    defaults_leaving = {book.course_id for book in moving if book.course_id and book.is_default}
    for course_id in source_courses | ({target_id} if target_id else set()):
        db.execute(update(Course).where(Course.id == course_id).values(
            notebook_order_revision=Course.notebook_order_revision + 1))

    next_slot = (db.scalar(select(func.max(Notebook.tree_slot)).where(
        Notebook.course_id == target_id, Notebook.deleted_at.is_(None))) or -1) + 1 if target_id else 0
    for book in moving:
        book.course_id = target_id
        book.tree_slot = next_slot if target_id else 0
        book.display_order = next_slot if target_id else 0
        book.order_revision = (target.notebook_order_revision + 1) if target else 0
        book.is_default = bool(target_id and next_slot == 0)
        if target_id:
            next_slot += 1
        db.execute(update(NotebookSection).where(
            NotebookSection.notebook_id == book.id,
        ).values(course_id=target_id))

    for course_id in defaults_leaving - ({target_id} if target_id else set()):
        replacement = db.scalar(select(Notebook).where(
            Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
            Notebook.id.not_in(payload.notebook_ids),
        ).order_by(Notebook.display_order, Notebook.id))
        if replacement:
            replacement.is_default = True
    db.commit()
    return {"action": "move", "affected": len(moving)}


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


@router.get("/notebooks/{notebook_id}/relations", response_model=list[NotebookRelationRead])
def list_notebook_relations(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    outgoing = db.scalars(select(NotebookRelation).where(
        NotebookRelation.source_notebook_id == notebook_id,
    )).all()
    incoming = db.scalars(select(NotebookRelation).where(
        NotebookRelation.target_notebook_id == notebook_id,
    )).all()
    relations = [
        {"id": rel.id, "source_notebook_id": rel.source_notebook_id,
         "target_notebook_id": rel.target_notebook_id,
         "related_notebook_id": rel.target_notebook_id,
         "related_notebook_title": db.get(Notebook, rel.target_notebook_id).title,
         "direction": "outgoing", "relation_type": rel.relation_type,
         "description": rel.description, "created_at": rel.created_at}
        for rel in outgoing
    ]
    relations.extend(
        {"id": rel.id, "source_notebook_id": rel.source_notebook_id,
         "target_notebook_id": rel.target_notebook_id,
         "related_notebook_id": rel.source_notebook_id,
         "related_notebook_title": db.get(Notebook, rel.source_notebook_id).title,
         "direction": "incoming", "relation_type": rel.relation_type,
         "description": rel.description, "created_at": rel.created_at}
        for rel in incoming
    )
    return sorted(relations, key=lambda rel: (rel["created_at"], rel["id"]), reverse=True)


@router.post("/notebooks/{notebook_id}/relations", response_model=NotebookRelationRead,
             status_code=201)
def create_notebook_relation(notebook_id: str, payload: NotebookRelationCreate,
                             db: Session = Depends(get_db)):
    source = db.get(Notebook, notebook_id)
    target = db.get(Notebook, payload.target_notebook_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(404, "源笔记不存在")
    if target is None or target.deleted_at is not None:
        raise HTTPException(404, "目标笔记不存在")
    if source.id == target.id:
        raise HTTPException(422, "笔记不能关联到自身")
    relation = NotebookRelation(
        source_notebook_id=source.id, target_notebook_id=target.id,
        relation_type=payload.relation_type.strip(), description=payload.description,
    )
    db.add(relation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "该关系已存在") from exc
    db.refresh(relation)
    return {"id": relation.id, "source_notebook_id": source.id,
            "target_notebook_id": target.id, "related_notebook_id": target.id,
            "related_notebook_title": target.title, "direction": "outgoing",
            "relation_type": relation.relation_type, "description": relation.description,
            "created_at": relation.created_at}


@router.delete("/notebooks/{notebook_id}/relations/{relation_id}", status_code=204)
def delete_notebook_relation(notebook_id: str, relation_id: str,
                             db: Session = Depends(get_db)):
    relation = db.get(NotebookRelation, relation_id)
    if relation is None or notebook_id not in (
        relation.source_notebook_id, relation.target_notebook_id,
    ):
        raise HTTPException(404, "笔记关系不存在")
    from app.forest.suppressions import suppress
    suppress(db, relation)
    db.delete(relation)
    db.commit()


def _cover_url(book: Notebook) -> str | None:
    return f"/api/v1/notebooks/{book.id}/cover" if book.cover_filename else None


def _summary(book: Notebook) -> dict:
    return {"id": book.id, "course_id": book.course_id, "title": book.title,
            "tree_slot": book.tree_slot, "display_order": book.display_order,
            "order_revision": book.order_revision, "is_default": book.is_default,
            "created_at": book.created_at, "updated_at": book.updated_at,
            "cover_url": _cover_url(book)}


@router.get("/notebooks/unbound", response_model=list[UnboundNotebookSummary])
def list_unbound_notebooks(db: Session = Depends(get_db)):
    books = db.scalars(select(Notebook).where(Notebook.course_id.is_(None), Notebook.deleted_at.is_(None)).order_by(
        Notebook.created_at.desc(), Notebook.id)).all()
    return [_summary(book) for book in books]


@router.post("/notebooks/unbound", response_model=UnboundNotebookSummary, status_code=201)
def create_unbound_notebook(payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "笔记名称不能为空")
    book = Notebook(course_id=None, title=title, tree_slot=0, is_default=False)
    db.add(book)
    db.commit()
    db.refresh(book)
    return _summary(book)


@router.get("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def get_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    return _summary(book)


@router.patch("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def rename_unbound_notebook(notebook_id: str, payload: NotebookTitleUpdate,
                            db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    book.title = payload.title.strip()
    db.commit()
    db.refresh(book)
    return _summary(book)


@router.delete("/notebooks/unbound/{notebook_id}", status_code=204)
def delete_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    active_jobs = db.scalar(select(func.count()).select_from(ProcessingJob).join(
        Material, ProcessingJob.material_id == Material.id).where(
        Material.notebook_id == notebook_id,
        ProcessingJob.status.in_(["pending", "processing"]))) or 0
    if active_jobs:
        raise HTTPException(409, "笔记仍有资料处理任务，完成或取消后再删除")
    from datetime import UTC, datetime

    from app.services.deletion import _checkpoint
    _checkpoint()
    book.deleted_at = datetime.now(UTC)
    book.is_default = False
    db.commit()


@router.get("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_unbound_document(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    stored = load_document(book.document_json)
    return {"schema_version": 2, "content": stored.content,
            "blocks": document_to_blocks(stored.content),
            "revision": book.document_revision, "updated_at": book.updated_at,
            "warning": stored.warning}


@router.put("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_unbound_document(notebook_id: str, payload: NotebookDocumentUpdate,
                         db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    if payload.blocks is not None and not load_document(book.document_json).legacy:
        raise HTTPException(409, "笔记已使用新版编辑器，请刷新页面后继续编辑")
    try:
        if payload.content is not None:
            content = payload.content
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise HTTPException(422, "正文块编号不能重复")
            content = legacy_blocks_to_document(blocks)
        _ensure_document_image_ownership(db, notebook_id, normalize_document(content))
        next_revision, stored = write_document(
            db, book, content, expected_revision=payload.expected_revision,
            origin="autosave", legacy_compatible=payload.blocks is not None,
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"schema_version": 2, "content": stored,
            "blocks": document_to_blocks(stored), "revision": next_revision,
            "updated_at": book.updated_at}


@router.get("/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_unbound_revisions(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    return list_snapshots(db, notebook_id)


@router.get("/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_unbound_revision(notebook_id: str, revision: int,
                          db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    return {"revision": snapshot.revision, "origin": snapshot.origin,
            "created_at": snapshot.created_at, "schema_version": 2,
            "content": stored.content}


@router.post("/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_unbound_revision(notebook_id: str, revision: int,
                             payload: NotebookRestoreRequest,
                             db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored_snapshot = load_document(snapshot.document_json)
    try:
        _restore_document_image_ownership(db, notebook_id, stored_snapshot.content, snapshot.id)
        next_revision, content = write_document(
            db, book, stored_snapshot.content,
            expected_revision=payload.expected_revision, origin="restore",
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        db.rollback()
        raise HTTPException(422, f"历史版本内容已失效：{exc}") from exc
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content), "revision": next_revision,
            "updated_at": book.updated_at}


@router.post("/notebooks/{notebook_id}/bind", response_model=NotebookSummary)
def bind_notebook(notebook_id: str, payload: NotebookBindRequest, db: Session = Depends(get_db)):
    course_id = payload.course_id
    course = ensure_course(db, course_id)
    claimed = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id.is_(None), Notebook.deleted_at.is_(None)).values(title=Notebook.title))
    if claimed.rowcount != 1:
        raise HTTPException(404, "未绑定的笔记不存在")
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    # Lock the course row before assigning the next permanent branch slot.
    next_order_revision = course.notebook_order_revision + 1
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=next_order_revision))
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course_id))
    book.course_id = course.id
    book.tree_slot = 0 if slot is None else slot + 1
    book.display_order = book.tree_slot
    book.order_revision = next_order_revision
    db.flush()
    db.execute(update(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).values(course_id=course.id))
    bound_book = book
    db.commit()
    db.refresh(bound_book)
    return _summary(bound_book)


@router.post("/notebooks/{notebook_id}/unbind", response_model=UnboundNotebookSummary)
def unbind_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    if book.course_id is None:
        return book
    old_course_id = book.course_id
    db.execute(update(Course).where(Course.id == old_course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))
    book.course_id = None
    book.tree_slot = 0
    book.display_order = 0
    book.order_revision = 0
    book.is_default = False
    db.execute(update(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).values(course_id=None))
    db.commit()
    db.refresh(book)
    return _summary(book)


def ensure_notebook(db: Session, course_id: str, notebook_id: str) -> Notebook:
    ensure_course(db, course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id != course_id or book.deleted_at is not None:
        raise HTTPException(404, "该课程中的笔记本不存在")
    return book


@router.get("/courses/{course_id}/notebooks", response_model=list[NotebookSummary])
def list_notebooks(course_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    return [_summary(book) for book in list_course_notebooks(db, course_id)
            if book.deleted_at is None]


@router.post("/courses/{course_id}/notebooks", response_model=NotebookSummary, status_code=201)
def create_notebook(course_id: str, payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "笔记本名称不能为空")
    # Acquire the SQLite write lock before reading the next persistent branch slot.
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision))
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course_id))
    book = Notebook(course_id=course_id, title=title, tree_slot=0 if slot is None else slot + 1,
                    display_order=0 if slot is None else slot + 1, is_default=slot is None)
    db.add(book)
    db.commit()
    db.refresh(book)
    return _summary(book)


@router.put("/notebooks/{notebook_id}/cover")
async def upload_notebook_cover(notebook_id: str, file: UploadFile = File(...),
                                db: Session = Depends(get_db)):
    import hashlib
    import uuid

    from app.notes.attachments import MAX_ATTACHMENT_BYTES, sniff_image_mime
    from app.services.image_assets import finalize_staged_image, write_staged_image

    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    mime = sniff_image_mime(data)
    if not data or len(data) > MAX_ATTACHMENT_BYTES or mime is None:
        raise HTTPException(413 if len(data) > MAX_ATTACHMENT_BYTES else 422,
                            "封面需为不超过 10 MB 的 PNG、JPEG、WebP 或 GIF 图片")
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[mime]
    asset_id = str(uuid.uuid4())
    name = f"{notebook_id}-{asset_id}{extension}"
    staging_path = write_staged_image(asset_id, data)
    old_cover = db.get(NotebookCoverAsset, notebook_id)
    asset = Asset(
        id=asset_id, source_type="user_upload", media_type="image", mime_type=mime,
        extension=extension, original_name=(file.filename or "cover")[:255],
        storage_key=f"notebook-covers/{notebook_id}/{asset_id}{extension}", byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), state="staging",
        created_at=utc_now(), verified_at=None,
    )
    db.add(asset)
    db.flush()
    owner_link = NotebookAsset(notebook_id=notebook_id, asset_id=asset_id, role="cover",
                               is_owner=True, created_at=utc_now())
    db.add(owner_link)
    db.flush()
    if old_cover:
        old_link = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == old_cover.asset_id,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        ))
        if old_link:
            old_link.detached_at = utc_now()
        db.delete(old_cover)
    db.add(NotebookCoverAsset(notebook_id=notebook_id, asset_id=asset_id,
                              owner_link_id=owner_link.id, created_at=utc_now()))
    book.cover_filename, book.cover_mime = name, mime
    try:
        db.commit()
    except Exception:
        db.rollback()
        staging_path.unlink(missing_ok=True)
        raise
    finalize_staged_image(db, asset)
    return {"cover_url": _cover_url(book)}


@router.get("/notebooks/{notebook_id}/cover")
def get_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None or book.cover_filename is None:
        raise HTTPException(404, "笔记封面不存在")
    cover = db.get(NotebookCoverAsset, notebook_id)
    asset = db.get(Asset, cover.asset_id) if cover else None
    try:
        owned = db.scalar(select(NotebookAsset.id).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset.id if asset is not None else False,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        )) if asset is not None else None
        path = storage_path(asset) if asset is not None and asset.state == "ready" and owned else None
    except AssetUnavailable:
        path = None
    if path is None:
        raise HTTPException(404, "笔记封面不存在")
    return FileResponse(path, media_type=asset.mime_type,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/notebooks/{notebook_id}/cover", status_code=204)
def delete_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None:
        raise HTTPException(404, "笔记不存在")
    cover = db.get(NotebookCoverAsset, notebook_id)
    asset = db.get(Asset, cover.asset_id) if cover else None
    if cover:
        link = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == cover.asset_id,
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
        ))
        if link:
            link.detached_at = utc_now()
        db.delete(cover)
    if asset:
        asset.state = "delete_pending"
    book.cover_filename = book.cover_mime = None
    db.commit()


@router.post("/notebooks/{notebook_id}/move", response_model=NotebookSummary)
def move_notebook(notebook_id: str, payload: NotebookMoveRequest, db: Session = Depends(get_db)):
    course = ensure_course(db, payload.course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    if book.course_id == course.id:
        raise HTTPException(409, "笔记已经属于该课程")
    db.execute(update(Course).where(Course.id == course.id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course.id))
    book.course_id = course.id
    book.tree_slot = 0 if slot is None else slot + 1
    book.display_order = book.tree_slot
    book.order_revision = course.notebook_order_revision + 1
    book.is_default = slot is None
    db.execute(update(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).values(course_id=course.id))
    db.commit()
    db.refresh(book)
    return _summary(book)


@router.delete("/courses/{course_id}/notebooks/{notebook_id}", status_code=204)
def delete_course_notebook(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    if book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    active_jobs = db.scalar(select(func.count()).select_from(ProcessingJob).join(
        Material, ProcessingJob.material_id == Material.id).where(
        Material.notebook_id == notebook_id,
        ProcessingJob.status.in_(["pending", "processing"]))) or 0
    if active_jobs:
        raise HTTPException(409, "笔记本仍有资料处理任务，完成或取消后再删除")
    from datetime import UTC, datetime

    from app.services.deletion import _checkpoint
    _checkpoint()
    book.deleted_at = datetime.now(UTC)
    book.is_default = False
    if db.scalar(select(func.count()).select_from(Notebook).where(
            Notebook.course_id == course_id, Notebook.deleted_at.is_(None))) == 0:
        replacement = db.scalar(select(Notebook).where(
            Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
            Notebook.id != notebook_id).order_by(Notebook.display_order, Notebook.id))
        if replacement:
            replacement.is_default = True
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))
    db.commit()


@router.get("/notebooks/deleted", response_model=list[NotebookSummary])
def list_deleted_notebooks(db: Session = Depends(get_db)):
    return [_summary(book) for book in db.scalars(select(Notebook).where(
        Notebook.deleted_at.is_not(None)).order_by(Notebook.deleted_at.desc())).all()]


@router.post("/notebooks/{notebook_id}/restore", response_model=NotebookSummary)
def restore_deleted_notebook(notebook_id: str, payload: NotebookRestoreDeletedRequest,
                             db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is None:
        raise HTTPException(404, "待恢复笔记不存在")
    if payload.course_id is None:
        book.course_id = None
        book.tree_slot = 0
        book.display_order = 0
        book.order_revision = 0
        book.is_default = False
        book.deleted_at = None
        db.commit(); db.refresh(book)
        return _summary(book)
    course = ensure_course(db, payload.course_id)
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(
        Notebook.course_id == course.id, Notebook.deleted_at.is_(None)))
    book.course_id = course.id
    book.tree_slot = 0 if slot is None else slot + 1
    book.display_order = book.tree_slot
    book.order_revision = course.notebook_order_revision + 1
    book.is_default = slot is None
    book.deleted_at = None
    db.execute(update(Course).where(Course.id == course.id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))
    db.commit(); db.refresh(book)
    return _summary(book)


@router.get("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def get_named_notebook(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    return notebook_outline(db, db.get(Course, course_id), book)


@router.patch("/courses/{course_id}/notebooks/{notebook_id}", response_model=NotebookRead)
def rename_notebook(course_id: str, notebook_id: str, payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    if not payload.title.strip():
        raise HTTPException(422, "笔记本名称不能为空")
    book.title = payload.title.strip()
    db.commit()
    return notebook_outline(db, db.get(Course, course_id), book)


@router.get("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_notebook_document(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    stored = load_document(book.document_json)
    return {"schema_version": 2, "content": stored.content,
            "blocks": document_to_blocks(stored.content),
            "revision": book.document_revision, "updated_at": book.updated_at,
            "warning": stored.warning}


@router.put("/courses/{course_id}/notebooks/{notebook_id}/document", response_model=NotebookDocumentRead)
def put_notebook_document(course_id: str, notebook_id: str, payload: NotebookDocumentUpdate,
                          db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    if payload.blocks is not None and not load_document(book.document_json).legacy:
        raise HTTPException(409, "笔记已使用新版编辑器，请刷新页面后继续编辑")
    try:
        if payload.content is not None:
            content = payload.content
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise HTTPException(422, "正文块编号不能重复")
            content = legacy_blocks_to_document(blocks)
        _ensure_document_image_ownership(db, notebook_id, normalize_document(content))
        next_revision, stored = write_document(
            db, book, content, expected_revision=payload.expected_revision,
            origin="autosave", legacy_compatible=payload.blocks is not None,
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"schema_version": 2, "content": stored,
            "blocks": document_to_blocks(stored),
            "revision": next_revision, "updated_at": book.updated_at}


@router.get("/notebooks/{notebook_id}/edit-suggestions",
            response_model=list[NotebookEditSuggestionRead])
def list_edit_suggestions(notebook_id: str, status: str | None = "pending",
                          db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    query = select(NotebookEditSuggestion).where(
        NotebookEditSuggestion.notebook_id == notebook_id,
    )
    if status:
        query = query.where(NotebookEditSuggestion.status == status)
    rows = db.scalars(query.order_by(
        NotebookEditSuggestion.created_at.desc()).limit(50)).all()
    result = []
    for row in rows:
        try:
            operations = json.loads(row.ops_json)
            proposed = load_document(row.proposed_document_json)
            result.append({
                "id": row.id, "notebook_id": row.notebook_id,
                "base_revision": row.base_revision, "rationale": row.rationale,
                "operations": operations if isinstance(operations, list) else [],
                "proposed_content": proposed.content if proposed.warning is None else None,
                "status": row.status, "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
            })
        except (TypeError, ValueError):
            result.append({
                "id": row.id, "notebook_id": row.notebook_id,
                "base_revision": row.base_revision, "rationale": row.rationale,
                "operations": [], "proposed_content": None,
                "status": row.status, "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
            })
    return result


@router.post("/notebooks/{notebook_id}/edit-suggestions/{suggestion_id}/review",
             response_model=NotebookDocumentRead)
def review_edit_suggestion(notebook_id: str, suggestion_id: str,
                           payload: NotebookEditSuggestionReview,
                           db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    suggestion = db.get(NotebookEditSuggestion, suggestion_id)
    if suggestion is None or suggestion.notebook_id != notebook_id:
        raise HTTPException(404, "修改建议不存在")
    if suggestion.status != "pending":
        raise HTTPException(409, "该建议已处理")
    now = utc_now()
    if payload.decision == "reject":
        changed = db.execute(update(NotebookEditSuggestion).where(
            NotebookEditSuggestion.id == suggestion_id,
            NotebookEditSuggestion.notebook_id == notebook_id,
            NotebookEditSuggestion.status == "pending",
        ).values(status="rejected", reviewed_at=now))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "该建议已处理")
        db.commit()
        stored = load_document(book.document_json)
        return {"schema_version": 2, "content": stored.content,
                "blocks": document_to_blocks(stored.content),
                "revision": book.document_revision, "updated_at": book.updated_at}
    if book.document_revision != suggestion.base_revision:
        suggestion.status = "stale"
        suggestion.reviewed_at = now
        db.commit()
        raise HTTPException(409, "笔记正文已变化，该建议已失效；请重新生成修改建议")
    if payload.expected_revision != book.document_revision:
        raise HTTPException(409, "笔记正文版本已变化，请刷新后重试")
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
        raise HTTPException(422, f"修改建议内容无效：{exc}") from exc
    if proposed is not None and proposed.warning:
        raise HTTPException(422, proposed.warning)
    _ensure_document_image_ownership(db, notebook_id, proposed_content)
    changed = db.execute(update(NotebookEditSuggestion).where(
        NotebookEditSuggestion.id == suggestion_id,
        NotebookEditSuggestion.notebook_id == notebook_id,
        NotebookEditSuggestion.status == "pending",
    ).values(status="applying"))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "该建议已处理")
    try:
        next_revision, content = write_document(
            db, book, proposed_content,
            expected_revision=payload.expected_revision, origin="ai_suggestion",
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    suggestion.status = "accepted" if payload.selected_operation_indices is None else "partially_accepted"
    suggestion.reviewed_at = now
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": next_revision, "updated_at": book.updated_at}


@router.get("/notebooks/{notebook_id}/blocks/{block_id}/sources",
            response_model=list[BlockSourceRead])
def get_block_sources(notebook_id: str, block_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    return block_source_payload(db, notebook_id, block_id)


@router.get("/courses/{course_id}/notebooks/{notebook_id}/sections")
def get_notebook_sections(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return [{
        "block_id": row.block_id, "heading": row.heading, "level": row.level,
        "order": row.order, "revision": row.revision, "excerpt": row.text[:300],
    } for row in sections_for_notebook(db, notebook_id)]


@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_notebook_revisions(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return list_snapshots(db, notebook_id)


@router.get("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_notebook_revision(course_id: str, notebook_id: str, revision: int,
                           db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    return {"revision": snapshot.revision, "origin": snapshot.origin,
            "created_at": snapshot.created_at, "schema_version": 2,
            "content": stored.content}


@router.post("/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}/restore",
             response_model=NotebookDocumentRead)
def restore_notebook_revision(course_id: str, notebook_id: str, revision: int,
                              payload: NotebookRestoreRequest, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    try:
        _restore_document_image_ownership(db, notebook_id, stored.content, snapshot.id)
        next_revision, content = write_document(
            db, book, stored.content,
            expected_revision=payload.expected_revision, origin="restore",
        )
    except DocumentConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except DocumentValidationError as exc:
        db.rollback()
        raise HTTPException(422, f"历史版本内容已失效：{exc}") from exc
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": next_revision, "updated_at": book.updated_at}


@router.post("/courses/{course_id}/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_notebook_attachment(course_id: str, notebook_id: str,
                                     file: UploadFile = File(...),
                                     db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, notebook_id=notebook_id,
                                      filename=file.filename or "image", data=data)
    except AttachmentRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.commit()
    db.refresh(attachment)
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}


@router.post("/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_unbound_notebook_attachment(notebook_id: str,
                                             file: UploadFile = File(...),
                                             db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise HTTPException(404, "未分类笔记不存在")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, notebook_id=notebook_id,
                                      filename=file.filename or "image", data=data)
    except AttachmentRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.commit()
    db.refresh(attachment)
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}


@router.get("/notebook-attachments/{attachment_id}")
def get_notebook_attachment(attachment_id: str, db: Session = Depends(get_db)):
    attachment = db.get(NotebookAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "附件不存在")
    if attachment.asset_id:
        try:
            owner = db.scalar(select(NotebookAsset).where(
                NotebookAsset.asset_id == attachment.asset_id,
                NotebookAsset.notebook_id == attachment.notebook_id,
                NotebookAsset.is_owner.is_(True),
            ))
            retained = bool(owner and db.scalar(select(func.count()).select_from(
                NotebookRevisionAsset
            ).where(
                NotebookRevisionAsset.notebook_id == attachment.notebook_id,
                NotebookRevisionAsset.asset_id == attachment.asset_id,
            )))
            if owner is None or (owner.detached_at is not None and not retained):
                raise AssetUnavailable("附件没有有效引用")
            asset = db.get(Asset, attachment.asset_id)
            if asset is None or asset.state != "ready":
                raise AssetUnavailable("附件资源不可用")
            path = storage_path(asset)
        except AssetUnavailable as exc:
            raise HTTPException(404, str(exc)) from exc
    else:
        try:
            path = attachment_path(attachment)
        except AttachmentRejected as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(404, "附件文件不存在")
    return FileResponse(path, media_type=attachment.mime,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})


@router.get("/assets/{asset_id}/content")
@router.get("/notebooks/{notebook_id}/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db),
):
    """Read a ready Notebook-owned asset using its stable resource ID.

    This local single-user app has no authenticated owner boundary; the owner
    link check enforces Notebook data integrity, not multi-user authorization.
    """
    if notebook_id is not None:
        notebook = db.get(Notebook, notebook_id)
        if notebook is None or notebook.deleted_at is not None:
            raise HTTPException(404, "笔记不存在")
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.is_owner.is_(True),
        ))
    else:
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ))
    if owner is None:
        raise HTTPException(404, "资源不存在")
    if notebook_id is None:
        notebook_id = owner.notebook_id
    asset = db.get(Asset, asset_id)
    if asset is None or asset.state != "ready":
        raise HTTPException(404, "资源不存在")
    if owner.detached_at is not None and not has_live_asset_references(db, asset, notebook_id):
        raise HTTPException(404, "资源已解除关联")
    try:
        path = storage_path(asset)
    except AssetUnavailable as exc:
        if "文件不存在" in str(exc):
            asset_row = db.get(Asset, asset_id)
            if asset_row is not None and asset_row.state == "ready":
                asset_row.state = "missing"
                db.commit()
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type=asset.mime_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})


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


@router.patch("/courses/{course_id}/notebooks/{notebook_id}/order", response_model=NotebookRead)
def reorder_named_notebook(course_id: str, notebook_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    return reorder(db, course_id, ensure_notebook(db, course_id, notebook_id), payload)


@router.get("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead | None)
def get_position(course_id: str, notebook_id: str, db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    return db.get(NotebookReadingPosition, notebook_id)


@router.put("/courses/{course_id}/notebooks/{notebook_id}/reading-position", response_model=ReadingPositionRead)
def put_position(course_id: str, notebook_id: str, payload: ReadingPositionUpdate, db: Session = Depends(get_db)):
    book = ensure_notebook(db, course_id, notebook_id)
    if payload.chapter_id is not None:
        material = db.get(Material, payload.chapter_id)
        if (material is None or material.notebook_id != notebook_id
                or material.deleted_at is not None):
            raise HTTPException(404, "阅读章节不存在或不属于当前笔记本")
    if payload.block_id is not None:
        stored = load_document(book.document_json)
        live = {
            (node.get("attrs") or {}).get("blockId")
            for node in stored.content.get("content") or []
            if isinstance(node, dict)
        }
        if payload.block_id not in live:
            raise HTTPException(404, "阅读位置对应的正文块不存在")
    values = payload.model_dump(exclude={"expected_revision"})
    values.update(revision=payload.expected_revision + 1, updated_at=utc_now())
    if payload.expected_revision == 0:
        db.add(NotebookReadingPosition(notebook_id=notebook_id, **values))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "阅读位置已变化，请刷新后重试") from exc
    else:
        result = db.execute(update(NotebookReadingPosition).where(
            NotebookReadingPosition.notebook_id == notebook_id,
            NotebookReadingPosition.revision == payload.expected_revision).values(**values))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "阅读位置已变化，请刷新后重试")
        db.commit()
    return db.get(NotebookReadingPosition, notebook_id)


@router.get("/courses/{course_id}/notebook", response_model=NotebookRead)
def get_notebook(course_id: str, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return notebook_outline(db, course, legacy_book(db, course))


def legacy_book(db: Session, course: Course) -> Notebook:
    book = default_notebook(db, course, create=False)
    if book is None:
        raise HTTPException(404, "此课程尚无笔记本，请先新建笔记本")
    return book


@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return reorder(db, course_id, legacy_book(db, course), payload)
