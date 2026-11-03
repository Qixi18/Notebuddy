from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    Course,
)
from app.schemas.api import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DeletionPreview,
)
from app.services.course_management import (
    course_overview as read_course_overview,
)
from app.services.course_management import (
    create_course as create_course_use_case,
)
from app.services.course_management import (
    delete_course as delete_course_use_case,
)
from app.services.course_management import (
    permanently_delete_course_by_id,
)
from app.services.course_management import (
    preview_course_deletion as preview_course_deletion_use_case,
)
from app.services.course_management import (
    rename_course as rename_course_use_case,
)
from app.services.course_management import (
    restore_course as restore_course_use_case,
)
from app.services.course_management import (
    visit_course as visit_course_use_case,
)

router = APIRouter()


@router.post("/courses/{course_id}/visit")
def visit_course(course_id: str, db: Session = Depends(get_db)) -> dict:
    return visit_course_use_case(db, course_id)


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    return create_course_use_case(db, name=payload.name.strip(), description=payload.description)



@router.get("/courses", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.deleted_at.is_(None)).order_by(Course.created_at.desc())).all())



@router.patch("/courses/{course_id}", response_model=CourseRead)
def rename_course(course_id: str, payload: CourseUpdate, db: Session = Depends(get_db)) -> Course:
    return rename_course_use_case(db, course_id, payload.name.strip())


@router.get("/courses/deleted", response_model=list[CourseRead])
def list_deleted_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.deleted_at.is_not(None)).order_by(Course.deleted_at.desc())).all())



@router.get("/courses/{course_id}/overview")
def course_overview(course_id: str, db: Session = Depends(get_db)) -> dict:
    """Course page data from Notebook body and Document IR quality."""
    return read_course_overview(db, course_id)

@router.get("/courses/{course_id}/deletion-preview", response_model=DeletionPreview)
def preview_course_deletion(course_id: str, db: Session = Depends(get_db)) -> dict:
    return preview_course_deletion_use_case(db, course_id)



@router.delete("/courses/{course_id}", response_model=DeletionPreview)
def delete_course(course_id: str, db: Session = Depends(get_db)) -> dict:
    return delete_course_use_case(db, course_id)



@router.post("/courses/{course_id}/restore", response_model=CourseRead)
def restore_course(course_id: str, db: Session = Depends(get_db)) -> Course:
    return restore_course_use_case(db, course_id)


@router.delete("/courses/{course_id}/permanent", status_code=204)
def purge_deleted_course(course_id: str, db: Session = Depends(get_db)) -> None:
    permanently_delete_course_by_id(db, course_id)
