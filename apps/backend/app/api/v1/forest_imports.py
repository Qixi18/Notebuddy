from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import CurriculumImport, ForestJob
from app.forest.curriculum import confirm_import, create_import
from app.forest.jobs import enqueue_relations, retry_job
from app.schemas.forest_imports import CurriculumConfirm, CurriculumImportRead, ForestJobRead
from app.services.uploads import UploadRejected

router = APIRouter()


def _record(db: Session, import_id: str) -> CurriculumImport:
    record = db.get(CurriculumImport, import_id)
    if record is None:
        raise HTTPException(404, "培养方案导入不存在")
    return record


def _read(db: Session, record: CurriculumImport) -> CurriculumImportRead:
    job_id = db.scalar(
        select(ForestJob.id)
        .where(ForestJob.curriculum_import_id == record.id)
        .order_by(ForestJob.created_at.desc())
        .limit(1)
    )
    return CurriculumImportRead(
        id=record.id,
        status=record.status,
        filename=record.filename,
        mode=record.mode,
        warnings=json.loads(record.warnings_json),
        rows=json.loads(record.rows_json),
        error_message=record.error_message,
        job_id=job_id,
    )


@router.get("/forest/curriculum-imports", response_model=list[CurriculumImportRead])
def list_imports(db: Session = Depends(get_db)):
    records = db.scalars(
        select(CurriculumImport)
        .order_by(CurriculumImport.created_at.desc(), CurriculumImport.id)
        .limit(20)
    ).all()
    return [_read(db, record) for record in records]


@router.post("/forest/curriculum-imports", response_model=CurriculumImportRead, status_code=201)
def import_curriculum(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    try:
        record = create_import(
            db,
            text=text,
            source=file.file if file else None,
            filename=file.filename if file else None,
        )
    except UploadRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return _read(db, record)


@router.get("/forest/curriculum-imports/{import_id}", response_model=CurriculumImportRead)
def get_import(import_id: str, db: Session = Depends(get_db)):
    return _read(db, _record(db, import_id))


@router.post("/forest/curriculum-imports/{import_id}/retry", response_model=CurriculumImportRead)
def retry_import(import_id: str, db: Session = Depends(get_db)):
    record = _record(db, import_id)
    job = db.scalar(
        select(ForestJob)
        .where(ForestJob.curriculum_import_id == record.id)
        .order_by(ForestJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise HTTPException(404, "培养方案任务不存在")
    retry_job(db, job)
    db.refresh(record)
    return _read(db, record)


@router.post("/forest/curriculum-imports/{import_id}/confirm")
def confirm_curriculum(import_id: str, payload: CurriculumConfirm, db: Session = Depends(get_db)):
    from app.forest.service import list_forest_courses

    confirm_import(db, _record(db, import_id), payload.rows)
    courses = list_forest_courses(db)
    db.commit()
    return {"courses": courses}


@router.post("/forest/courses/{course_id}/suggest-relations", response_model=ForestJobRead)
def suggest_relations(course_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    job = enqueue_relations(db, course_id, explicit=True)
    if job is None:
        raise HTTPException(409, "课程还没有真实笔记，请先导入课件并生成笔记")
    db.commit()
    db.refresh(job)
    return job


@router.get("/forest/jobs/{job_id}", response_model=ForestJobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(ForestJob, job_id)
    if job is None:
        raise HTTPException(404, "森林任务不存在")
    if job.course_id:
        ensure_course(db, job.course_id)
    return job


@router.get("/forest/courses/{course_id}/latest-job", response_model=ForestJobRead | None)
def get_latest_course_forest_job(course_id: str, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    return db.scalar(
        select(ForestJob)
        .where(ForestJob.course_id == course_id, ForestJob.kind == "cross_course_relations")
        .order_by(ForestJob.created_at.desc(), ForestJob.id.desc())
        .limit(1)
    )


@router.post("/forest/jobs/{job_id}/retry", response_model=ForestJobRead)
def retry_forest_job(job_id: str, db: Session = Depends(get_db)):
    return retry_job(db, get_job(job_id, db))
