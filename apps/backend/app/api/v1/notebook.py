from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Course, Material, Note, Notebook, NotebookReadingPosition, utc_now
from app.notes.notebook import default_notebook, list_course_notebooks, notebook_outline
from app.schemas.notebook import (
    ChapterContentRead,
    NotebookOrderUpdate,
    NotebookRead,
    NotebookSummary,
    NotebookTitleUpdate,
    ReadingPositionRead,
    ReadingPositionUpdate,
)

router = APIRouter()


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
