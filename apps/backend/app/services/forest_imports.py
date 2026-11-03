"""Application use cases for Forest curriculum imports and durable jobs."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CurriculumImport, ForestCourseProfile, ForestJob
from app.forest.curriculum import CurriculumError, confirm_import, create_import
from app.forest.curriculum_processing import job_snapshot
from app.forest.curriculum_revert import revert_import, revert_preview
from app.forest.errors import CurriculumOperationError
from app.forest.jobs import retry_job
from app.forest.notebook_relations import enqueue_notebook_relations
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_course
from app.services.uploads import UploadRejected


def _record(db: Session, import_id: str) -> CurriculumImport:
    record = db.get(CurriculumImport, import_id)
    if record is None:
        raise ApplicationError(404, "培养方案导入不存在")
    return record


def _read(db: Session, record: CurriculumImport) -> dict:
    job = db.scalar(select(ForestJob).where(
        ForestJob.curriculum_import_id == record.id
    ).order_by(ForestJob.created_at.desc()).limit(1))
    snapshot = job_snapshot(job)
    rows = json.loads(record.rows_json)
    for row in rows:
        if row.get("existing_course_id") and row.get("expected_profile_revision") is None:
            profile = db.get(ForestCourseProfile, row["existing_course_id"])
            row["expected_profile_revision"] = profile.revision if profile else 0
    return {
        "id": record.id, "status": record.status, "filename": record.filename,
        "mode": record.mode, "warnings": json.loads(record.warnings_json), "rows": rows,
        "error_message": record.error_message, "job_id": job.id if job else None,
        "progress": job.progress if job else 0,
        "processing_route": snapshot.get("processing_route", "standard"),
        "phase": snapshot.get("phase"),
        "can_revert": record.status == "confirmed" and bool(snapshot.get("confirmation", {}).get("courses")),
    }


def list_curriculum_imports(db: Session) -> list[dict]:
    records = db.scalars(select(CurriculumImport).order_by(
        CurriculumImport.created_at.desc(), CurriculumImport.id).limit(20)).all()
    return [_read(db, record) for record in records]


def get_curriculum_import(db: Session, import_id: str) -> dict:
    return _read(db, _record(db, import_id))


def create_curriculum_import(db: Session, *, text: str | None, source,
                             filename: str | None, processing_route: str | None) -> dict:
    try:
        record = create_import(db, text=text, source=source, filename=filename,
                               processing_route=processing_route)
    except UploadRejected as exc:
        raise ApplicationError(exc.status_code, str(exc)) from exc
    return _read(db, record)


def retry_curriculum_import(db: Session, import_id: str) -> dict:
    record = _record(db, import_id)
    job = db.scalar(select(ForestJob).where(
        ForestJob.curriculum_import_id == record.id
    ).order_by(ForestJob.created_at.desc()).limit(1))
    if job is None:
        raise ApplicationError(404, "培养方案任务不存在")
    try:
        retry_job(db, job)
        db.commit()
    except CurriculumError as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    db.refresh(record)
    return _read(db, record)


def confirm_curriculum_import(db: Session, import_id: str, rows: list) -> dict:
    record = _record(db, import_id)
    try:
        confirm_import(db, record, rows)
        from app.forest.service import list_forest_courses
        courses = list_forest_courses(db)
        db.commit()
    except CurriculumOperationError as exc:
        db.rollback()
        raise ApplicationError(exc.status_code, exc.detail) from exc
    except Exception:
        db.rollback()
        raise
    return {"courses": courses, "import": _read(db, record)}


def preview_curriculum_revert(db: Session, import_id: str) -> dict:
    try:
        return revert_preview(db, _record(db, import_id))
    except CurriculumOperationError as exc:
        raise ApplicationError(exc.status_code, exc.detail) from exc


def revert_curriculum_import(db: Session, import_id: str) -> dict:
    record = _record(db, import_id)
    try:
        revert_import(db, record)
    except CurriculumOperationError as exc:
        raise ApplicationError(exc.status_code, exc.detail) from exc
    db.refresh(record)
    return _read(db, record)


def get_forest_job(db: Session, job_id: str) -> ForestJob:
    job = db.get(ForestJob, job_id)
    if job is None:
        raise ApplicationError(404, "森林任务不存在")
    if job.course_id:
        require_course(db, job.course_id)
    return job


def latest_forest_job(db: Session, course_id: str) -> ForestJob | None:
    require_course(db, course_id)
    return db.scalar(select(ForestJob).where(
        ForestJob.course_id == course_id, ForestJob.kind == "notebook_relations"
    ).order_by(ForestJob.created_at.desc(), ForestJob.id.desc()).limit(1))


def suggest_forest_relations(db: Session, course_id: str) -> ForestJob:
    require_course(db, course_id)
    job = enqueue_notebook_relations(db, course_id)
    if job is None:
        raise ApplicationError(409, "至少需要两门课程有可用笔记正文，才能生成跨课关联")
    try:
        if job.status == "failed":
            retry_job(db, job)
        db.commit()
    except CurriculumError as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    db.refresh(job)
    return job


def retry_forest_job(db: Session, job_id: str) -> ForestJob:
    job = get_forest_job(db, job_id)
    try:
        retry_job(db, job)
        db.commit()
    except CurriculumError as exc:
        db.rollback()
        raise ApplicationError(409, str(exc)) from exc
    db.refresh(job)
    return job
