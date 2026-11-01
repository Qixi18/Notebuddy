"""Notebook 路由 · lifecycle。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    AssetProcessingJob,
    Course,
    Material,
    Notebook,
    NotebookGenerationJob,
    NotebookSection,
    ProcessingJob,
)
from app.notes.notebook import list_course_notebooks, notebook_outline
from app.schemas.notebook import (
    NotebookBindRequest,
    NotebookBulkManageRequest,
    NotebookMoveRequest,
    NotebookOrderUpdate,
    NotebookRead,
    NotebookRestoreDeletedRequest,
    NotebookSummary,
    NotebookTitleUpdate,
    UnboundNotebookSummary,
)
from app.services.deletion import DeletionConflict, permanently_delete_notebook

from .common import (
    _summary,
    ensure_notebook,
    legacy_book,
    reorder,
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
    from app.forest.notebook_relations import enqueue_notebook_relations

    enqueue_notebook_relations(db, course.id, notebook_id=book.id)
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

@router.delete("/notebooks/{notebook_id}/permanent", status_code=204)
def purge_deleted_notebook(notebook_id: str, db: Session = Depends(get_db)) -> None:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is None:
        raise HTTPException(404, "回收站中没有这篇笔记")
    try:
        permanently_delete_notebook(db, book)
    except DeletionConflict as exc:
        raise HTTPException(409, str(exc)) from exc

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

@router.patch("/courses/{course_id}/notebooks/{notebook_id}/order", response_model=NotebookRead)
def reorder_named_notebook(course_id: str, notebook_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    return reorder(db, course_id, ensure_notebook(db, course_id, notebook_id), payload)

@router.get("/courses/{course_id}/notebook", response_model=NotebookRead)
def get_notebook(course_id: str, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return notebook_outline(db, course, legacy_book(db, course))

@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    return reorder(db, course_id, legacy_book(db, course), payload)
