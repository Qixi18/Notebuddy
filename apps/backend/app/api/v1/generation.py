from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.model_utils import new_id
from app.db.models import (
    Notebook,
    NotebookAsset,
    NotebookGenerationJob,
)
from app.generation.context import GenerationInputError, build_snapshot
from app.schemas.generation import NotebookGenerationCreate, NotebookGenerationJobRead
from app.workers.notebook_generation_worker import PROMPT_VERSION

router = APIRouter()


def _job_read(db: Session, job: NotebookGenerationJob) -> dict:
    plan = None
    if job.knowledge_plan_json:
        try:
            raw = json.loads(job.knowledge_plan_json)
            plan = {
                "new_count": raw.get("new_count"),
                "extend_count": raw.get("extend_count"),
                "skip_count": raw.get("skip_count"),
                "batches": len(raw.get("batches") or []),
            }
        except (TypeError, ValueError):
            plan = None
    try:
        parse_run_ids = json.loads(job.parse_run_ids_json or "[]")
    except (TypeError, ValueError):
        parse_run_ids = []
    return {
        "id": job.id, "notebook_id": job.notebook_id, "status": job.status,
        "base_document_revision": job.base_document_revision, "model": job.model,
        "prompt_version": job.prompt_version, "attempt_count": job.attempt_count,
        "error_code": job.error_code, "error_message": job.error_message,
        "created_at": job.created_at, "updated_at": job.updated_at,
        "finished_at": job.finished_at, "generator": job.generator,
        "parse_run_ids": parse_run_ids, "plan": plan,
    }


def _same_generation_request(
    job: NotebookGenerationJob,
    *,
    notebook_id: str,
    asset_ids: list[str],
) -> bool:
    if job.notebook_id != notebook_id:
        return False
    try:
        snapshot = json.loads(job.input_snapshot_json)
        stored_ids = [source["asset_id"] for source in snapshot["sources"]]
    except (KeyError, TypeError, ValueError):
        return False
    return stored_ids == asset_ids


@router.post("/notebooks/{notebook_id}/generation-jobs", response_model=NotebookGenerationJobRead,
             status_code=202)
def create_generation_job(
    notebook_id: str,
    payload: NotebookGenerationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    key = (idempotency_key or str(uuid.uuid4())).strip()[:100]
    if not key:
        raise HTTPException(422, "幂等键不能为空")
    requested = payload.asset_ids
    if requested:
        if len(set(requested)) != len(requested):
            raise HTTPException(422, "资料资源不能重复选择")
        asset_ids = requested
    else:
        asset_ids = list(db.scalars(select(NotebookAsset.asset_id).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.role == "source_material",
            NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ).order_by(NotebookAsset.created_at, NotebookAsset.id)).all())
    if not asset_ids:
        raise HTTPException(409, "没有可用于生成的资料")

    existing = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == notebook_id,
        NotebookGenerationJob.idempotency_key == key,
    ))
    if existing is not None:
        if not _same_generation_request(existing, notebook_id=notebook_id, asset_ids=asset_ids):
            raise HTTPException(409, "幂等键已用于不同的资料")
        return _job_read(db, existing)

    for asset_id in asset_ids:
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == asset_id,
            NotebookAsset.role == "source_material",
            NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ))
        if owner is None:
            raise HTTPException(422, f"输入资源不可用或不属于当前笔记：{asset_id}")

    try:
        snapshot = build_snapshot(db, notebook, asset_ids)
    except GenerationInputError as exc:
        raise HTTPException(409, {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }) from exc

    request_fingerprint = hashlib.sha256(json.dumps({
        "notebook_id": notebook_id,
        "base_document_revision": notebook.document_revision,
        "current_document_sha256": hashlib.sha256(
            json.dumps(snapshot["current_document"], ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "sources": [{
            "asset_id": source["asset_id"],
            "parse_run_id": source["parse_run_id"],
            "ir_fingerprint": source["ir_fingerprint"],
            "quality": source["quality"]["status"],
        } for source in snapshot["sources"]],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    now = datetime.now(UTC)
    generator = settings.notebook_generator
    job = NotebookGenerationJob(
        id=new_id(), notebook_id=notebook_id, idempotency_key=key,
        request_fingerprint=request_fingerprint,
        status="pending", base_document_revision=notebook.document_revision,
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        model=settings.deepseek_model if generator == "deepseek" else generator,
        prompt_version=PROMPT_VERSION, schema_version=2, attempt_count=0,
        generator=generator, generator_version="1",
        parse_run_ids_json=json.dumps(
            [source["parse_run_id"] for source in snapshot["sources"]], ensure_ascii=False),
        ir_fingerprints_json=json.dumps(
            {source["asset_id"]: source["ir_fingerprint"] for source in snapshot["sources"]},
            ensure_ascii=False),
        created_at=now, updated_at=now,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(NotebookGenerationJob).where(
            NotebookGenerationJob.notebook_id == notebook_id,
            NotebookGenerationJob.idempotency_key == key,
        ))
        if duplicate is not None and _same_generation_request(
            duplicate, notebook_id=notebook_id, asset_ids=asset_ids,
        ):
            return _job_read(db, duplicate)
        raise HTTPException(409, "生成任务创建冲突") from exc
    db.refresh(job)
    return _job_read(db, job)


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
