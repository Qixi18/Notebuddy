from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Course,
    Material,
    Note,
    Notebook,
    NotebookAttachment,
    NotebookReadingPosition,
    utc_now,
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
    dump_document,
    legacy_blocks_to_document,
    load_document,
    normalize_document,
    validate_document,
)
from app.notes.history import get_snapshot, list_snapshots, record_snapshot
from app.notes.notebook import default_notebook, list_course_notebooks, notebook_outline
from app.schemas.notebook import (
    ChapterContentRead,
    NotebookAttachmentRead,
    NotebookBindRequest,
    NotebookDocumentRead,
    NotebookDocumentUpdate,
    NotebookOrderUpdate,
    NotebookRead,
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


@router.get("/notebooks/unbound", response_model=list[UnboundNotebookSummary])
def list_unbound_notebooks(db: Session = Depends(get_db)):
    return db.scalars(select(Notebook).where(Notebook.course_id.is_(None)).order_by(
        Notebook.created_at.desc(), Notebook.id)).all()


@router.post("/notebooks/unbound", response_model=UnboundNotebookSummary, status_code=201)
def create_unbound_notebook(payload: NotebookTitleUpdate, db: Session = Depends(get_db)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "笔记名称不能为空")
    book = Notebook(course_id=None, title=title, tree_slot=0, is_default=False)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


@router.get("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def get_unbound_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    return book


@router.patch("/notebooks/unbound/{notebook_id}", response_model=UnboundNotebookSummary)
def rename_unbound_notebook(notebook_id: str, payload: NotebookTitleUpdate,
                            db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    book.title = payload.title.strip()
    db.commit()
    db.refresh(book)
    return book


@router.get("/notebooks/unbound/{notebook_id}/document", response_model=NotebookDocumentRead)
def get_unbound_document(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
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
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未绑定的笔记不存在")
    try:
        content = validate_document(normalize_document(payload.content)) if payload.content is not None else \
            validate_document(legacy_blocks_to_document([block.model_dump() for block in payload.blocks or []]))
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if attachment_ids(content):
        for attachment_id in attachment_ids(content):
            attachment = db.get(NotebookAttachment, attachment_id)
            if attachment is None or attachment.notebook_id != notebook_id:
                raise HTTPException(422, "图片附件不属于当前笔记")
    now = utc_now()
    next_revision = payload.expected_revision + 1
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook_id,
        Notebook.course_id.is_(None),
        Notebook.document_revision == payload.expected_revision,
    ).values(document_json=dump_document(content), document_revision=next_revision, updated_at=now))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记已在别处更新，请先刷新后再保存")
    record_snapshot(db, notebook_id, next_revision, content)
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content), "revision": next_revision,
            "updated_at": now}


@router.get("/notebooks/{notebook_id}/revisions",
            response_model=list[NotebookRevisionSummary])
def list_unbound_revisions(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未分类笔记不存在")
    return list_snapshots(db, notebook_id)


@router.get("/notebooks/{notebook_id}/revisions/{revision}",
            response_model=NotebookRevisionRead)
def read_unbound_revision(notebook_id: str, revision: int,
                          db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
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
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未分类笔记不存在")
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    try:
        content = validate_document(normalize_document(stored.content))
    except DocumentValidationError as exc:
        raise HTTPException(422, f"历史版本内容已失效：{exc}") from exc
    now = utc_now()
    next_revision = payload.expected_revision + 1
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id.is_(None),
        Notebook.document_revision == payload.expected_revision,
    ).values(document_json=dump_document(content),
             document_revision=next_revision, updated_at=now))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记已在别处更新，请先刷新后再恢复")
    record_snapshot(db, notebook_id, next_revision, content, origin="restore")
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content), "revision": next_revision,
            "updated_at": now}


@router.post("/notebooks/{notebook_id}/bind", response_model=NotebookSummary)
def bind_notebook(notebook_id: str, payload: NotebookBindRequest, db: Session = Depends(get_db)):
    course_id = payload.course_id
    course = ensure_course(db, course_id)
    claimed = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id.is_(None)).values(title=Notebook.title))
    if claimed.rowcount != 1:
        raise HTTPException(404, "未绑定的笔记不存在")
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None:
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
    db.execute(update(NotebookAttachment).where(
        NotebookAttachment.notebook_id == book.id,
        NotebookAttachment.course_id.is_(None),
    ).values(course_id=course.id))
    db.flush()
    bound_book = book
    db.commit()
    db.refresh(bound_book)
    return bound_book


@router.post("/notebooks/{notebook_id}/unbind", response_model=UnboundNotebookSummary)
def unbind_notebook(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None:
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
    db.execute(update(NotebookAttachment).where(
        NotebookAttachment.notebook_id == notebook_id,
    ).values(course_id=None))
    db.commit()
    db.refresh(book)
    return book


def ensure_notebook(db: Session, course_id: str, notebook_id: str) -> Notebook:
    ensure_course(db, course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id != course_id:
        raise HTTPException(404, "该课程中的笔记本不存在")
    return book


@router.get("/courses/{course_id}/notebooks", response_model=list[NotebookSummary])
def list_notebooks(course_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    return list_course_notebooks(db, course_id)


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
    return book


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
            content = validate_document(normalize_document(payload.content))
        else:
            blocks = [block.model_dump() for block in payload.blocks or []]
            if len({block["id"] for block in blocks}) != len(blocks):
                raise HTTPException(422, "正文块编号不能重复")
            content = validate_document(legacy_blocks_to_document(blocks))
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc

    for attachment_id in attachment_ids(content):
        attachment = db.get(NotebookAttachment, attachment_id)
        if attachment is None or attachment.notebook_id != notebook_id:
            raise HTTPException(422, "图片附件不属于当前笔记")

    now = utc_now()
    next_revision = payload.expected_revision + 1
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id == course_id,
        Notebook.document_revision == payload.expected_revision,
    ).values(document_json=dump_document(content, legacy_compatible=payload.blocks is not None),
             document_revision=next_revision, updated_at=now))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记已在别处更新，请先刷新后再保存")
    record_snapshot(db, notebook_id, next_revision, content)
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": next_revision, "updated_at": now}


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
    ensure_notebook(db, course_id, notebook_id)
    snapshot = get_snapshot(db, notebook_id, revision)
    if snapshot is None:
        raise HTTPException(404, "历史版本不存在")
    stored = load_document(snapshot.document_json)
    try:
        content = validate_document(normalize_document(stored.content))
    except DocumentValidationError as exc:
        raise HTTPException(422, f"历史版本内容已失效：{exc}") from exc

    now = utc_now()
    next_revision = payload.expected_revision + 1
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id == course_id,
        Notebook.document_revision == payload.expected_revision,
    ).values(document_json=dump_document(content),
             document_revision=next_revision, updated_at=now))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记已在别处更新，请刷新后再恢复")
    record_snapshot(db, notebook_id, next_revision, content, origin="restore")
    db.commit()
    return {"schema_version": 2, "content": content,
            "blocks": document_to_blocks(content),
            "revision": next_revision, "updated_at": now}


@router.post("/courses/{course_id}/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_notebook_attachment(course_id: str, notebook_id: str,
                                     file: UploadFile = File(...),
                                     db: Session = Depends(get_db)):
    ensure_notebook(db, course_id, notebook_id)
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, course_id=course_id, notebook_id=notebook_id,
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
    if book is None or book.course_id is not None:
        raise HTTPException(404, "未分类笔记不存在")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    try:
        attachment = store_attachment(db, course_id=None, notebook_id=notebook_id,
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
    try:
        path = attachment_path(attachment)
    except AttachmentRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(404, "附件文件不存在")
    return FileResponse(path, media_type=attachment.mime,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})


def chapter_content(db: Session, course_id: str, book: Notebook, material_id: str):
    material = db.get(Material, material_id)
    if (material is None or material.course_id != course_id or material.notebook_id != book.id
            or material.deleted_at is not None):
        raise HTTPException(404, "该笔记本中的章节不存在或已移除")
    return {"material_id": material_id, "sections": db.scalars(select(Note).where(
        Note.course_id == course_id, Note.notebook_id == book.id, Note.material_id == material_id
    ).order_by(Note.section_order, Note.created_at, Note.id)).all()}


@router.get("/courses/{course_id}/notebooks/{notebook_id}/chapters/{material_id}", response_model=ChapterContentRead)
def get_named_chapter(course_id: str, notebook_id: str, material_id: str, db: Session = Depends(get_db)):
    return chapter_content(db, course_id, ensure_notebook(db, course_id, notebook_id), material_id)


def reorder(db: Session, course_id: str, book: Notebook, payload: NotebookOrderUpdate):
    result = db.execute(update(Notebook).where(
        Notebook.id == book.id, Notebook.order_revision == payload.expected_order_revision
    ).values(order_revision=Notebook.order_revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "章节已变化，请刷新目录后重新排序")
    materials = db.scalars(select(Material).where(Material.course_id == course_id,
                                                 Material.notebook_id == book.id,
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
    ensure_notebook(db, course_id, notebook_id)
    if payload.chapter_id is not None:
        material = db.get(Material, payload.chapter_id)
        if (material is None or material.course_id != course_id or material.notebook_id != notebook_id
                or material.deleted_at is not None):
            raise HTTPException(404, "阅读章节不存在或不属于当前笔记本")
    if payload.note_id is not None:
        note = db.get(Note, payload.note_id)
        if (note is None or note.course_id != course_id or note.notebook_id != notebook_id
                or note.material_id != payload.chapter_id):
            raise HTTPException(404, "阅读小节不存在或不属于当前章节")
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


@router.get("/courses/{course_id}/notebook/chapters/{material_id}", response_model=ChapterContentRead)
def get_chapter(course_id: str, material_id: str, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return chapter_content(db, course_id, legacy_book(db, course), material_id)


@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return reorder(db, course_id, legacy_book(db, course), payload)
