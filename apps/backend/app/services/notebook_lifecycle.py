"""Notebook lifecycle application rules shared by delete endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    AssetProcessingJob,
    Course,
    Material,
    Notebook,
    NotebookGenerationJob,
    NotebookSection,
    ProcessingJob,
)
from app.notes.notebook import default_notebook, list_course_notebooks, notebook_outline
from app.services.deletion import DeletionConflict, _checkpoint, permanently_delete_notebook
from app.services.errors import ApplicationError
from app.services.notebook_order import reorder_notebook as reorder_notebook_service
from app.services.resource_scopes import require_notebook


def list_unbound_notebooks(db: Session) -> list[Notebook]:
    return list(db.scalars(select(Notebook).where(
        Notebook.course_id.is_(None), Notebook.deleted_at.is_(None),
    ).order_by(Notebook.created_at.desc(), Notebook.id)).all())


def get_course_notebooks(db: Session, course_id: str) -> list[Notebook]:
    _active_course(db, course_id)
    return list_course_notebooks(db, course_id)


def get_unbound_notebook(db: Session, notebook_id: str) -> Notebook:
    return require_notebook(db, notebook_id, unbound=True)


def list_deleted_notebooks(db: Session) -> list[Notebook]:
    return list(db.scalars(select(Notebook).where(
        Notebook.deleted_at.is_not(None),
    ).order_by(Notebook.deleted_at.desc())).all())


def get_notebook_outline(db: Session, course_id: str, notebook_id: str | None = None):
    course = _active_course(db, course_id)
    if notebook_id is None:
        book = default_notebook(db, course, create=False)
        if book is None:
            raise ApplicationError(404, "此课程尚无笔记本，请先新建笔记本")
    else:
        book = require_notebook(db, notebook_id, course_id=course_id)
    return notebook_outline(db, course, book)


def reorder_notebook_outline(
    db: Session, course_id: str, notebook_id: str | None,
    material_ids: list[str], expected_order_revision: int,
):
    course = _active_course(db, course_id)
    if notebook_id is None:
        book = default_notebook(db, course, create=False)
        if book is None:
            raise ApplicationError(404, "此课程尚无笔记本，请先新建笔记本")
    else:
        book = require_notebook(db, notebook_id, course_id=course_id)
    reorder_notebook_service(db, book, material_ids, expected_order_revision)
    return notebook_outline(db, course, book)


def permanently_delete_notebook_service(db: Session, notebook_id: str) -> None:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is None:
        raise ApplicationError(404, "回收站中没有这篇笔记")
    try:
        permanently_delete_notebook(db, notebook)
    except DeletionConflict as exc:
        raise ApplicationError(409, str(exc)) from exc


def create_unbound_notebook(db: Session, title: str) -> Notebook:
    normalized = title.strip()
    if not normalized:
        raise ApplicationError(422, "笔记名称不能为空")
    book = Notebook(course_id=None, title=normalized, tree_slot=0, is_default=False)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def rename_notebook(db: Session, notebook_id: str, title: str, *, course_id: str | None = None) -> Notebook:
    book = db.get(Notebook, notebook_id)
    if (book is None or book.deleted_at is not None
            or (course_id is None and book.course_id is not None)
            or (course_id is not None and book.course_id != course_id)):
        raise ApplicationError(404, "笔记不存在")
    if course_id is not None:
        _active_course(db, course_id)
    normalized = title.strip()
    if not normalized:
        raise ApplicationError(422, "笔记本名称不能为空")
    book.title = normalized
    db.commit()
    db.refresh(book)
    return book


def _active_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is not None:
        raise ApplicationError(404, "课程不存在")
    return course


def _ensure_course_default(db: Session, course_id: str, excluding_ids: list[str] | None = None) -> None:
    has_default = db.scalar(select(Notebook.id).where(
        Notebook.course_id == course_id,
        Notebook.deleted_at.is_(None),
        Notebook.is_default.is_(True),
    ).limit(1))
    if has_default is not None:
        return
    candidates = select(Notebook).where(
        Notebook.course_id == course_id,
        Notebook.deleted_at.is_(None),
    )
    if excluding_ids:
        candidates = candidates.where(Notebook.id.not_in(excluding_ids))
    replacement = db.scalar(candidates.order_by(Notebook.display_order, Notebook.id).limit(1))
    if replacement is not None:
        replacement.is_default = True


def bind_notebook(db: Session, notebook_id: str, course_id: str) -> Notebook:
    course = _active_course(db, course_id)
    claimed = db.execute(update(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id.is_(None), Notebook.deleted_at.is_(None),
    ).values(title=Notebook.title))
    if claimed.rowcount != 1:
        raise ApplicationError(404, "未绑定的笔记不存在")
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise ApplicationError(404, "未绑定的笔记不存在")
    next_order_revision = course.notebook_order_revision + 1
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=next_order_revision,
    ))
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
    db.commit()
    db.refresh(book)
    return book


def unbind_notebook(db: Session, notebook_id: str) -> Notebook:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    if book.course_id is None:
        return book
    _active_course(db, book.course_id)
    old_course_id = book.course_id
    was_default = book.is_default
    db.execute(update(Course).where(Course.id == old_course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1,
    ))
    book.course_id = None
    book.tree_slot = 0
    book.display_order = 0
    book.order_revision = 0
    book.is_default = False
    db.execute(update(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).values(course_id=None))
    db.flush()
    if was_default:
        _ensure_course_default(db, old_course_id)
    from app.forest.notebook_relations import enqueue_notebook_relations

    enqueue_notebook_relations(db, old_course_id)
    db.commit()
    db.refresh(book)
    return book


def create_course_notebook(db: Session, course_id: str, title: str) -> Notebook:
    course = _active_course(db, course_id)
    normalized = title.strip()
    if not normalized:
        raise ApplicationError(422, "笔记本名称不能为空")
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision,
    ))
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course_id))
    book = Notebook(course_id=course.id, title=normalized,
                    tree_slot=0 if slot is None else slot + 1,
                    display_order=0 if slot is None else slot + 1,
                    is_default=slot is None)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def move_notebook(db: Session, notebook_id: str, course_id: str) -> Notebook:
    course = _active_course(db, course_id)
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    if book.course_id is not None:
        _active_course(db, book.course_id)
    old_course_id = book.course_id
    was_default = book.is_default
    if book.course_id == course.id:
        raise ApplicationError(409, "笔记已经属于该课程")
    db.execute(update(Course).where(Course.id == course.id).values(
        notebook_order_revision=Course.notebook_order_revision + 1,
    ))
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(Notebook.course_id == course.id))
    book.course_id = course.id
    book.tree_slot = 0 if slot is None else slot + 1
    book.display_order = book.tree_slot
    book.order_revision = course.notebook_order_revision + 1
    book.is_default = slot is None
    db.execute(update(NotebookSection).where(
        NotebookSection.notebook_id == notebook_id,
    ).values(course_id=course.id))
    db.flush()
    if was_default and old_course_id is not None:
        _ensure_course_default(db, old_course_id)
    from app.forest.notebook_relations import enqueue_notebook_relations

    for affected_course_id in {old_course_id, course.id} - {None}:
        enqueue_notebook_relations(db, affected_course_id)
    db.commit()
    db.refresh(book)
    return book


def restore_deleted_notebook(db: Session, notebook_id: str, course_id: str | None) -> Notebook:
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is None:
        raise ApplicationError(404, "待恢复笔记不存在")
    if course_id is None:
        book.course_id = None
        book.tree_slot = 0
        book.display_order = 0
        book.order_revision = 0
        book.is_default = False
        book.deleted_at = None
        db.commit()
        db.refresh(book)
        return book
    course = _active_course(db, course_id)
    slot = db.scalar(select(func.max(Notebook.tree_slot)).where(
        Notebook.course_id == course.id, Notebook.deleted_at.is_(None),
    ))
    book.course_id = course.id
    book.tree_slot = 0 if slot is None else slot + 1
    book.display_order = book.tree_slot
    book.order_revision = course.notebook_order_revision + 1
    book.is_default = slot is None
    book.deleted_at = None
    db.execute(update(Course).where(Course.id == course.id).values(
        notebook_order_revision=Course.notebook_order_revision + 1,
    ))
    db.commit()
    db.refresh(book)
    return book


def ensure_notebook_has_no_active_jobs(db: Session, notebook_ids: list[str]) -> None:
    """Reject soft deletion while any material, image, or generation job is active."""
    if not notebook_ids:
        return
    active_jobs = db.scalar(select(func.count()).select_from(ProcessingJob).join(
        Material, ProcessingJob.material_id == Material.id).where(
        Material.notebook_id.in_(notebook_ids),
        ProcessingJob.status.in_(["pending", "processing", "cancel_requested"]))) or 0
    active_jobs += db.scalar(select(func.count()).select_from(AssetProcessingJob).where(
        AssetProcessingJob.notebook_id.in_(notebook_ids),
        AssetProcessingJob.status.in_(["pending", "processing", "cancel_requested"]))) or 0
    active_jobs += db.scalar(select(func.count()).select_from(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id.in_(notebook_ids),
        NotebookGenerationJob.status.in_(["pending", "processing", "cancel_requested"]))) or 0
    if active_jobs:
        raise ApplicationError(409, "笔记本仍有资料处理或生成任务，完成或取消后再删除")


def bulk_manage_notebooks(
    db: Session, notebook_ids: list[str], *, action: str, course_id: str | None,
) -> dict:
    books = list(db.scalars(select(Notebook).where(
        Notebook.id.in_(notebook_ids), Notebook.deleted_at.is_(None),
    )).all())
    if len(books) != len(notebook_ids):
        raise ApplicationError(404, "部分笔记不存在或已在回收站，请刷新列表后重试")

    if action == "delete":
        for book in books:
            if book.course_id is not None:
                _active_course(db, book.course_id)
        ensure_notebook_has_no_active_jobs(db, notebook_ids)
        _checkpoint()
        deleted_at = datetime.now(UTC)
        for book in books:
            book.deleted_at = deleted_at
            book.is_default = False
        # Clear the partial unique default index before promoting replacements.
        db.flush()
        changed_courses = {book.course_id for book in books if book.course_id}
        for changed_course_id in changed_courses:
            _ensure_course_default(db, changed_course_id, notebook_ids)
            db.execute(update(Course).where(Course.id == changed_course_id).values(
                notebook_order_revision=Course.notebook_order_revision + 1,
            ))
        db.commit()
        return {"action": "delete", "affected": len(books)}

    target = _active_course(db, course_id) if course_id else None
    target_id = target.id if target else None
    moving = [book for book in books if book.course_id != target_id]
    if not moving:
        return {"action": "move", "affected": 0}

    source_courses = {book.course_id for book in moving if book.course_id}
    defaults_leaving = {book.course_id for book in moving if book.course_id and book.is_default}
    for changed_course_id in source_courses | ({target_id} if target_id else set()):
        db.execute(update(Course).where(Course.id == changed_course_id).values(
            notebook_order_revision=Course.notebook_order_revision + 1,
        ))

    last_slot = db.scalar(select(func.max(Notebook.tree_slot)).where(
        Notebook.course_id == target_id, Notebook.deleted_at.is_(None),
    )) if target_id else None
    next_slot = (last_slot + 1) if last_slot is not None else 0
    for book in moving:
        book.course_id = target_id
        book.tree_slot = next_slot if target_id else 0
        book.display_order = next_slot if target_id else 0
        book.order_revision = (target.notebook_order_revision + 1) if target else 0
        book.is_default = bool(target_id and next_slot == 0)
        if target_id:
            next_slot += 1
        db.execute(
            NotebookSection.__table__.update().where(
                NotebookSection.notebook_id == book.id,
            ).values(course_id=target_id)
        )

    # Move default owners out of their source course before promoting replacements.
    db.flush()
    for changed_course_id in defaults_leaving - ({target_id} if target_id else set()):
        _ensure_course_default(db, changed_course_id, notebook_ids)
    from app.forest.notebook_relations import enqueue_notebook_relations

    for affected_course_id in source_courses | ({target_id} if target_id else set()):
        enqueue_notebook_relations(db, affected_course_id)
    db.commit()
    return {"action": "move", "affected": len(moving)}


def delete_unbound_notebook(db: Session, notebook_id: str) -> None:
    book = db.get(Notebook, notebook_id)
    if book is None or book.course_id is not None or book.deleted_at is not None:
        raise ApplicationError(404, "未分类笔记不存在")
    ensure_notebook_has_no_active_jobs(db, [notebook_id])
    _checkpoint()
    book.deleted_at = datetime.now(UTC)
    book.is_default = False
    db.commit()


def delete_course_notebook(db: Session, course_id: str, notebook_id: str) -> None:
    book = db.scalar(select(Notebook).where(
        Notebook.id == notebook_id, Notebook.course_id == course_id,
    ))
    if book is None or book.deleted_at is not None:
        raise ApplicationError(404, "笔记不存在")
    _active_course(db, course_id)
    ensure_notebook_has_no_active_jobs(db, [notebook_id])
    _checkpoint()
    book.deleted_at = datetime.now(UTC)
    book.is_default = False
    # Free the partial unique index before promoting the replacement.
    db.flush()
    _ensure_course_default(db, course_id, [notebook_id])
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1,
    ))
    db.commit()
