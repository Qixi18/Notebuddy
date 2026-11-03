from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.forest_imports import CurriculumConfirm, CurriculumImportRead, ForestJobRead
from app.services.forest_imports import (
    confirm_curriculum_import,
    create_curriculum_import,
    get_curriculum_import,
    get_forest_job,
    latest_forest_job,
    list_curriculum_imports,
    preview_curriculum_revert,
    retry_curriculum_import,
    suggest_forest_relations,
)
from app.services.forest_imports import (
    retry_forest_job as retry_forest_job_use_case,
)
from app.services.forest_imports import (
    revert_curriculum_import as revert_curriculum_import_use_case,
)

router = APIRouter()


@router.get("/forest/curriculum-imports", response_model=list[CurriculumImportRead])
def list_imports(db: Session = Depends(get_db)):
    return list_curriculum_imports(db)


@router.post("/forest/curriculum-imports", response_model=CurriculumImportRead, status_code=201)
def import_curriculum(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    processing_route: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    return create_curriculum_import(
        db, text=text, source=file.file if file else None,
        filename=file.filename if file else None, processing_route=processing_route,
    )


@router.get("/forest/curriculum-imports/{import_id}", response_model=CurriculumImportRead)
def get_import(import_id: str, db: Session = Depends(get_db)):
    return get_curriculum_import(db, import_id)


@router.post("/forest/curriculum-imports/{import_id}/retry", response_model=CurriculumImportRead)
def retry_import(import_id: str, db: Session = Depends(get_db)):
    return retry_curriculum_import(db, import_id)


@router.post("/forest/curriculum-imports/{import_id}/confirm")
def confirm_curriculum(import_id: str, payload: CurriculumConfirm, db: Session = Depends(get_db)):
    return confirm_curriculum_import(db, import_id, payload.rows)


@router.get("/forest/curriculum-imports/{import_id}/revert-preview")
def preview_revert(import_id: str, db: Session = Depends(get_db)):
    return preview_curriculum_revert(db, import_id)


@router.post("/forest/curriculum-imports/{import_id}/revert", response_model=CurriculumImportRead)
def revert_curriculum(import_id: str, db: Session = Depends(get_db)):
    return revert_curriculum_import_use_case(db, import_id)


@router.post("/forest/courses/{course_id}/suggest-relations", response_model=ForestJobRead)
def suggest_relations(course_id: str, db: Session = Depends(get_db)):
    return suggest_forest_relations(db, course_id)


@router.get("/forest/jobs/{job_id}", response_model=ForestJobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return get_forest_job(db, job_id)


@router.get("/forest/courses/{course_id}/latest-job", response_model=ForestJobRead | None)
def get_latest_course_forest_job(course_id: str, db: Session = Depends(get_db)):
    return latest_forest_job(db, course_id)


@router.post("/forest/jobs/{job_id}/retry", response_model=ForestJobRead)
def retry_forest_job(job_id: str, db: Session = Depends(get_db)):
    return retry_forest_job_use_case(db, job_id)
