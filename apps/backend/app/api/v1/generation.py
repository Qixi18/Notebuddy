from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook, NotebookGenerationJob
from app.schemas.generation import NotebookGenerationCreate, NotebookGenerationJobRead
from app.services.generation_jobs import _job_read
from app.services.generation_jobs import create_generation_job as _create_generation_job

router = APIRouter()


@router.post("/notebooks/{notebook_id}/generation-jobs", response_model=NotebookGenerationJobRead,
             status_code=202)
def create_generation_job(
    notebook_id: str,
    payload: NotebookGenerationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return _create_generation_job(db, notebook_id, payload, idempotency_key)


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
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    if job.status not in {"failed", "conflict", "cancelled"}:
        raise HTTPException(409, "任务当前不可重试")
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    snapshot = json.loads(job.input_snapshot_json)
    snapshot["base_document_revision"] = notebook.document_revision
    from app.generation.context import current_outline
    from app.notes.document import load_document

    snapshot["current_document"] = load_document(notebook.document_json).content
    snapshot["current_outline"] = current_outline(snapshot["current_document"])
    # Keep attempts monotonic: a delayed result from a previous worker must
    # never become eligible again after retry and claim.
    now = datetime.now(UTC)
    retried = db.execute(update(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job.id,
        NotebookGenerationJob.status.in_(("failed", "conflict", "cancelled")),
        NotebookGenerationJob.attempt_count == job.attempt_count,
    ).values(
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        base_document_revision=notebook.document_revision, status="pending",
        error_code=None, error_message=None, knowledge_plan_json=None,
        source_map_json=None, finished_at=None, updated_at=now,
    ).execution_options(synchronize_session=False))
    if not retried.rowcount:
        db.rollback()
        raise HTTPException(409, "任务状态已更新，请刷新后重试")
    from app.db.models import NotebookGenerationInput

    db.query(NotebookGenerationInput).filter(
        NotebookGenerationInput.generation_job_id == job.id,
        NotebookGenerationInput.status == "generation_failed",
    ).update({
        NotebookGenerationInput.status: "generating",
        NotebookGenerationInput.error_code: None,
        NotebookGenerationInput.error_message: None,
        NotebookGenerationInput.updated_at: now,
    }, synchronize_session=False)
    db.commit()
    db.refresh(job)
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/cancel",
             response_model=NotebookGenerationJobRead)
def cancel_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    now = datetime.now(UTC)
    cancelled = db.execute(update(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job.id,
        NotebookGenerationJob.status == "pending",
    ).values(status="cancelled", finished_at=now, updated_at=now)
      .execution_options(synchronize_session=False))
    if cancelled.rowcount:
        from app.services.notebook_generation_inputs import cancel_generation_inputs

        cancel_generation_inputs(db, job.id)
    else:
        requested = db.execute(update(NotebookGenerationJob).where(
            NotebookGenerationJob.id == job.id,
            NotebookGenerationJob.status == "processing",
        ).values(status="cancel_requested", updated_at=now)
          .execution_options(synchronize_session=False))
        if not requested.rowcount:
            db.rollback()
            raise HTTPException(409, "任务已进入不可取消状态")
    db.commit()
    db.refresh(job)
    return _job_read(db, job)
