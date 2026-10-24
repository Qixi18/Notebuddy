from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Course,
    utc_now,
)
from app.forest.service import ensure_profile, prepare_course_restore
from app.schemas.api import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DeletionPreview,
)
from app.services.deletion import (
    DeletionConflict,
    impact_preview,
    soft_delete_course,
)

router = APIRouter()


@router.post("/courses/{course_id}/visit")
def visit_course(course_id: str, db: Session = Depends(get_db)) -> dict:
    course = ensure_course(db, course_id)
    course.last_opened_at = utc_now()
    db.commit()
    return {"last_opened_at": course.last_opened_at}


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    course = Course(name=payload.name.strip(), description=payload.description)
    db.add(course)
    db.flush()
    ensure_profile(db, course)
    db.commit()
    db.refresh(course)
    return course



@router.get("/courses", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.deleted_at.is_(None)).order_by(Course.created_at.desc())).all())



@router.patch("/courses/{course_id}", response_model=CourseRead)
def rename_course(course_id: str, payload: CourseUpdate, db: Session = Depends(get_db)) -> Course:
    course = ensure_course(db, course_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="课程名称不能为空")
    course.name = name
    db.commit()
    db.refresh(course)
    return course


@router.get("/courses/deleted", response_model=list[CourseRead])
def list_deleted_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.deleted_at.is_not(None)).order_by(Course.deleted_at.desc())).all())



@router.get("/courses/{course_id}/deletion-preview", response_model=DeletionPreview)
def preview_course_deletion(course_id: str, db: Session = Depends(get_db)) -> dict:
    ensure_course(db, course_id)
    return impact_preview(db, course_id=course_id)



@router.delete("/courses/{course_id}", response_model=DeletionPreview)
def delete_course(course_id: str, db: Session = Depends(get_db)) -> dict:
    course = ensure_course(db, course_id)
    try:
        return soft_delete_course(db, course)
    except DeletionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc



@router.post("/courses/{course_id}/restore", response_model=CourseRead)
def restore_course(course_id: str, db: Session = Depends(get_db)) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is None:
        raise HTTPException(status_code=404, detail="待恢复课程不存在")
    prepare_course_restore(db, course)
    course.deleted_at = None
    db.commit()
    db.refresh(course)
    return course
