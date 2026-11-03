from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook, NotebookGenerationJob
from app.schemas.generation import NotebookGenerationCreate, NotebookGenerationJobRead
from app.services.generation_jobs import _job_read
from app.services.generation_jobs import cancel_generation_job as _cancel_generation_job
from app.services.generation_jobs import create_generation_job as _create_generation_job
from app.services.generation_jobs import retry_generation_job as _retry_generation_job

router = APIRouter()


@router.post("/notebooks/{notebook_id}/generation-jobs", response_model=NotebookGenerationJobRead,
             status_code=202)
def create_generation_job(
    notebook_id: str,
    payload: NotebookGenerationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return _create_generation_job(db, notebook_id, payload.asset_ids, idempotency_key)


@router.get("/notebooks/{notebook_id}/generation-jobs", response_model=list[NotebookGenerationJobRead])
def list_generation_jobs(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    jobs = db.scalars(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == notebook_id,
    ).order_by(NotebookGenerationJob.created_at.desc()).limit(100)).all()
    return [_job_read(db, job) for job in jobs]


@router.get("/notebooks/{notebook_id}/generation-jobs/{job_id}", response_model=NotebookGenerationJobRead)
def get_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/retry",
             response_model=NotebookGenerationJobRead, status_code=202)
def retry_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    return _retry_generation_job(db, notebook_id, job_id)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/cancel",
             response_model=NotebookGenerationJobRead)
def cancel_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    return _cancel_generation_job(db, notebook_id, job_id)
