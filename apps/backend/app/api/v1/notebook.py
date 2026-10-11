from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Course, Material, Note
from app.notes.notebook import notebook_outline
from app.schemas.notebook import ChapterContentRead, NotebookOrderUpdate, NotebookRead

router = APIRouter()


@router.get("/courses/{course_id}/notebook", response_model=NotebookRead)
def get_notebook(course_id: str, db: Session = Depends(get_db)):
    return notebook_outline(db, ensure_course(db, course_id))


@router.get("/courses/{course_id}/notebook/chapters/{material_id}", response_model=ChapterContentRead)
def get_chapter(course_id: str, material_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    material = db.get(Material, material_id)
    if material is None or material.course_id != course_id or material.deleted_at is not None:
        raise HTTPException(404, "该课程中的章节不存在或已移除")
    return {"material_id": material_id, "sections": db.scalars(select(Note).where(
        Note.course_id == course_id, Note.material_id == material_id
    ).order_by(Note.section_order, Note.created_at, Note.id)).all()}


@router.patch("/courses/{course_id}/notebook/order", response_model=NotebookRead)
def reorder_notebook(course_id: str, payload: NotebookOrderUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    result = db.execute(update(Course).where(
        Course.id == course_id, Course.notebook_order_revision == payload.expected_order_revision
    ).values(notebook_order_revision=Course.notebook_order_revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "章节已变化，请刷新目录后重新排序")
    materials = db.scalars(select(Material).where(Material.course_id == course_id,
                                                 Material.deleted_at.is_(None))).all()
    ids = payload.material_ids
    if len(set(ids)) != len(ids) or set(ids) != {m.id for m in materials}:
        db.rollback()
        raise HTTPException(422, "顺序必须包含当前课程全部章节，且不得重复")
    positions = {material_id: i for i, material_id in enumerate(ids)}
    for material in materials:
        material.chapter_order = positions[material.id]
    db.commit()
    db.refresh(course)
    return notebook_outline(db, course)
