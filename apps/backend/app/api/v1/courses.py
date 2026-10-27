from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    Asset,
    Course,
    NotebookGenerationJob,
    NotebookSection,
    utc_now,
)
from app.document_processing.service import current_run, latest_run
from app.forest.service import ensure_profile, prepare_course_restore
from app.schemas.api import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DeletionPreview,
)
from app.services.course_scope import materials_for_course, notebooks_for_course
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



@router.get("/courses/{course_id}/overview")
def course_overview(course_id: str, db: Session = Depends(get_db)) -> dict:
    """Course page data from Notebook body and Document IR quality."""

    course = ensure_course(db, course_id)
    notebooks = notebooks_for_course(db, course_id)
    section_counts = dict(db.execute(
        select(NotebookSection.notebook_id, func.count())
        .where(NotebookSection.notebook_id.in_([book.id for book in notebooks]))
        .group_by(NotebookSection.notebook_id)
    ).all()) if notebooks else {}
    materials = materials_for_course(db, course_id)
    material_rows = []
    needs_attention = 0
    for material in materials:
        asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
        run = current_run(db, asset.id) if asset is not None else None
        latest = run or (latest_run(db, asset.id) if asset is not None else None)
        quality = None
        if run is not None:
            import json

            from app.document_processing.ir import QualityReport

            quality = QualityReport.from_dict(json.loads(run.quality_json or "{}"))
        if material.status == "failed" or (
            quality is not None and not quality.generation_allowed
        ):
            needs_attention += 1
        material_rows.append({
            "id": material.id,
            "title": material.lecture_title,
            "filename": material.original_filename,
            "status": material.status,
            "page_count": material.page_count,
            "asset_id": asset.id if asset is not None else None,
            "parse_run_id": run.id if run is not None else (latest.id if latest else None),
            "quality_status": run.quality_status if run is not None else None,
            "generation_allowed": quality.generation_allowed if quality else False,
            "quality_reason": (
                quality.generation_block_reason if quality else
                (latest.error_message if latest is not None and latest.status == "failed" else None)
            ),
            "deleted_at": material.deleted_at,
        })
    jobs = db.scalars(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id.in_([book.id for book in notebooks]),
    ).order_by(NotebookGenerationJob.created_at.desc()).limit(10)).all() if notebooks else []
    job_rows = [{
        "id": job.id, "notebook_id": job.notebook_id, "status": job.status,
        "error_code": job.error_code, "error_message": job.error_message,
        "generator": job.generator, "created_at": job.created_at,
        "finished_at": job.finished_at,
    } for job in jobs]
    return {
        "course_id": course.id,
        "name": course.name,
        "counts": {
            "notebooks": len(notebooks),
            "sections": sum(section_counts.values()),
            "materials": len([item for item in materials if item.deleted_at is None]),
            "materials_needing_attention": needs_attention,
            "generation_running": sum(1 for job in job_rows if job["status"] in {"pending", "processing"}),
            "generation_failed": sum(1 for job in job_rows if job["status"] == "failed"),
        },
        "notebooks": [{
            "id": book.id, "title": book.title, "revision": book.document_revision,
            "sections": int(section_counts.get(book.id, 0)), "updated_at": book.updated_at,
        } for book in notebooks],
        "materials": material_rows,
        "generation_jobs": job_rows,
    }

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
