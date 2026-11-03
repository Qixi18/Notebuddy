"""Course lifecycle transactions and aggregated course overview queries."""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Course, NotebookGenerationJob, NotebookSection, utc_now
from app.document_processing.ir import QualityReport
from app.document_processing.service import current_run, latest_run
from app.forest.service import ensure_profile, prepare_course_restore
from app.services.course_scope import materials_for_course, notebooks_for_course
from app.services.deletion import impact_preview, permanently_delete_course, soft_delete_course
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_course


def visit_course(db: Session, course_id: str) -> dict:
    course = require_course(db, course_id)
    course.last_opened_at = utc_now()
    db.commit()
    return {"last_opened_at": course.last_opened_at}


def create_course(db: Session, *, name: str, description: str | None) -> Course:
    course = Course(name=name, description=description)
    db.add(course)
    db.flush()
    ensure_profile(db, course, auto_home=True)
    db.commit()
    db.refresh(course)
    return course


def rename_course(db: Session, course_id: str, name: str) -> Course:
    course = require_course(db, course_id)
    if not name:
        raise ApplicationError(400, "课程名称不能为空")
    course.name = name
    db.commit()
    db.refresh(course)
    return course


def course_overview(db: Session, course_id: str) -> dict:
    course = require_course(db, course_id)
    notebooks = notebooks_for_course(db, course_id)
    section_counts = dict(db.execute(
        select(NotebookSection.notebook_id, func.count())
        .where(NotebookSection.notebook_id.in_([book.id for book in notebooks]))
        .group_by(NotebookSection.notebook_id)
    ).all()) if notebooks else {}
    materials = materials_for_course(db, course_id)
    material_rows, needs_attention = [], 0
    for material in materials:
        asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
        run = current_run(db, asset.id) if asset is not None else None
        latest = run or (latest_run(db, asset.id) if asset is not None else None)
        quality = QualityReport.from_dict(json.loads(run.quality_json or "{}")) if run else None
        if material.status == "failed" or (quality is not None and not quality.generation_allowed):
            needs_attention += 1
        material_rows.append({
            "id": material.id, "title": material.lecture_title,
            "filename": material.original_filename, "status": material.status,
            "page_count": material.page_count, "asset_id": asset.id if asset else None,
            "parse_run_id": run.id if run else (latest.id if latest else None),
            "quality_status": run.quality_status if run else None,
            "generation_allowed": quality.generation_allowed if quality else False,
            "quality_reason": (quality.generation_block_reason if quality else
                (latest.error_message if latest and latest.status == "failed" else None)),
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
        "course_id": course.id, "name": course.name,
        "counts": {
            "notebooks": len(notebooks), "sections": sum(section_counts.values()),
            "materials": sum(item.deleted_at is None for item in materials),
            "materials_needing_attention": needs_attention,
            "generation_running": sum(row["status"] in {"pending", "processing"} for row in job_rows),
            "generation_failed": sum(row["status"] == "failed" for row in job_rows),
        },
        "notebooks": [{"id": book.id, "title": book.title,
                       "revision": book.document_revision,
                       "sections": int(section_counts.get(book.id, 0)),
                       "updated_at": book.updated_at} for book in notebooks],
        "materials": material_rows, "generation_jobs": job_rows,
    }


def preview_course_deletion(db: Session, course_id: str) -> dict:
    require_course(db, course_id)
    return impact_preview(db, course_id=course_id)


def delete_course(db: Session, course_id: str) -> dict:
    course = require_course(db, course_id)
    return soft_delete_course(db, course)


def restore_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is None:
        raise ApplicationError(404, "待恢复课程不存在")
    prepare_course_restore(db, course)
    course.deleted_at = None
    db.commit()
    db.refresh(course)
    return course


def permanently_delete_course_by_id(db: Session, course_id: str) -> None:
    course = db.get(Course, course_id)
    if course is None or course.deleted_at is None:
        raise ApplicationError(404, "回收站中没有这门课程")
    permanently_delete_course(db, course)
