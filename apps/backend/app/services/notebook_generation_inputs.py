"""Durable Notebook upload grouping and per-Asset generation orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    AssetProcessingJob,
    Material,
    NotebookAsset,
    NotebookGenerationInput,
    NotebookGenerationJob,
    NotebookUploadBatch,
    ProcessingJob,
)

BATCH_IDLE_CLOSE = timedelta(minutes=2)


def cancel_generation_inputs(db: Session, job_id: str) -> None:
    """Keep upload status and the cancelled generation task in agreement."""

    db.query(NotebookGenerationInput).filter(
        NotebookGenerationInput.generation_job_id == job_id,
        NotebookGenerationInput.status == "generating",
    ).update({
        NotebookGenerationInput.status: "generation_failed",
        NotebookGenerationInput.error_code: "cancelled",
        NotebookGenerationInput.error_message: "生成已取消；已有正文保持不变，可重新尝试",
        NotebookGenerationInput.updated_at: datetime.now(UTC),
    }, synchronize_session=False)


def ensure_upload_batch(
    db: Session, notebook_id: str, batch_id: str | None, *, close_if_new: bool = False,
) -> NotebookUploadBatch:
    now = datetime.now(UTC)
    identity = (batch_id or new_id()).strip()
    if not identity or len(identity) > 36:
        raise HTTPException(422, "上传批次编号不合法")
    batch = db.get(NotebookUploadBatch, identity)
    if batch is not None:
        if batch.notebook_id != notebook_id:
            raise HTTPException(409, "上传批次不属于当前笔记")
        if batch.closed_at is not None:
            raise HTTPException(409, "上传批次已关闭")
        batch.updated_at = now
        return batch
    batch = NotebookUploadBatch(
        id=identity, notebook_id=notebook_id, created_at=now, updated_at=now,
        closed_at=now if close_if_new else None,
    )
    db.add(batch)
    db.flush()
    return batch


def register_generation_input(
    db: Session, *, notebook_id: str, asset_id: str, batch_id: str,
    parse_kind: str, parse_job_id: str | None,
) -> NotebookGenerationInput:
    row = db.scalar(select(NotebookGenerationInput).where(
        NotebookGenerationInput.asset_id == asset_id,
    ))
    now = datetime.now(UTC)
    batch = db.get(NotebookUploadBatch, batch_id)
    if batch is None or batch.notebook_id != notebook_id:
        raise HTTPException(409, "上传批次不存在或不属于当前笔记")
    batch.updated_at = now
    if row is None:
        row = NotebookGenerationInput(
            id=new_id(), notebook_id=notebook_id, asset_id=asset_id, batch_id=batch_id,
            parse_kind=parse_kind, parse_job_id=parse_job_id, status="waiting_parse",
            created_at=now, updated_at=now,
        )
        db.add(row)
    elif row.status not in {"completed", "generating", "generation_failed"}:
        row.batch_id = batch_id
        row.parse_kind = parse_kind
        row.parse_job_id = parse_job_id
        row.parse_result_fingerprint = None
        row.status = "waiting_parse"
        row.error_code = row.error_message = None
        row.finished_at = None
        row.updated_at = now
    return row


def close_upload_batch(db: Session, notebook_id: str, batch_id: str) -> NotebookUploadBatch:
    batch = db.get(NotebookUploadBatch, batch_id)
    if batch is None or batch.notebook_id != notebook_id:
        raise HTTPException(404, "上传批次不存在")
    batch.closed_at = batch.closed_at or datetime.now(UTC)
    batch.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


def batch_status(db: Session, batch: NotebookUploadBatch) -> dict:
    rows = db.scalars(select(NotebookGenerationInput).where(
        NotebookGenerationInput.batch_id == batch.id,
    ).order_by(NotebookGenerationInput.created_at, NotebookGenerationInput.asset_id)).all()
    if any(row.status in {"waiting_parse", "parsing"} for row in rows):
        status = "parsing"
    elif any(row.status in {"ready", "generating"} for row in rows):
        status = "generating"
    elif rows and all(row.status == "completed" for row in rows):
        status = "completed"
    elif any(row.status in {"parse_failed", "generation_failed"} for row in rows):
        status = "partial_failure"
    else:
        status = "open" if batch.closed_at is None else "waiting_parse"
    jobs = db.scalars(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == batch.notebook_id,
        NotebookGenerationJob.id.in_([row.generation_job_id for row in rows if row.generation_job_id]),
    )).all() if any(row.generation_job_id for row in rows) else []
    return {
        "id": batch.id, "notebook_id": batch.notebook_id, "status": status,
        "created_at": batch.created_at, "updated_at": batch.updated_at,
        "closed_at": batch.closed_at,
        "inputs": [{
            "asset_id": row.asset_id, "parse_job_id": row.parse_job_id,
            "parse_result_fingerprint": row.parse_result_fingerprint,
            "generation_job_id": row.generation_job_id, "status": row.status,
            "error_code": row.error_code, "error_message": row.error_message,
            "retry_count": row.retry_count,
        } for row in rows],
        "generation_jobs": [{"id": job.id, "status": job.status} for job in jobs],
    }


def _parse_state(db: Session, asset_id: str) -> tuple[str | None, str | None, str | None]:
    """Return (fingerprint, error_code, error_message) from the Document IR.

    Generation readiness is never inferred from ``Material.course_id`` or from
    leftover page rows; the current ParseRun quality is authoritative.
    """

    from app.document_processing.ir import QualityReport
    from app.document_processing.service import current_run, latest_run

    run = current_run(db, asset_id)
    if run is None:
        latest = latest_run(db, asset_id)
        if latest is not None and latest.status == "failed":
            return None, (latest.error_code or "parse_failed"), (latest.error_message or "资料解析失败")
        return None, "parse_incomplete", "解析尚未完成"
    if run.status != "completed":
        return None, (run.error_code or "parse_failed"), (run.error_message or "资料解析失败")
    try:
        quality = QualityReport.from_dict(json.loads(run.quality_json or "{}"))
    except (TypeError, ValueError):
        quality = QualityReport()
    if not quality.generation_allowed:
        return None, "parse_quality_insufficient", (
            quality.generation_block_reason or "解析质量不足，未生成正文"
        )
    return run.fingerprint, None, None


def _reconcile_missing_inputs(db: Session) -> None:
    assets = db.scalars(select(Asset).join(NotebookAsset, NotebookAsset.asset_id == Asset.id).where(
        Asset.upload_batch_id.is_not(None),
        NotebookAsset.role == "source_material",
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    )).all()
    for asset in assets:
        if db.scalar(select(NotebookGenerationInput.id).where(
            NotebookGenerationInput.asset_id == asset.id,
        )) is not None:
            continue
        batch = db.get(NotebookUploadBatch, asset.upload_batch_id)
        owner = db.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset.id, NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ))
        if batch is None or owner is None:
            continue
        if asset.media_type == "image":
            job = db.scalar(select(AssetProcessingJob).where(
                AssetProcessingJob.asset_id == asset.id,
            ).order_by(AssetProcessingJob.created_at.desc(), AssetProcessingJob.id.desc()).limit(1))
            kind = "image"
        else:
            material = db.scalar(select(Material).where(Material.asset_id == asset.id))
            job = db.scalar(select(ProcessingJob).where(
                ProcessingJob.material_id == (material.id if material else ""),
            ).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc()).limit(1))
            kind = "material"
        if job is not None:
            register_generation_input(
                db, notebook_id=batch.notebook_id, asset_id=asset.id, batch_id=batch.id,
                parse_kind=kind, parse_job_id=job.id,
            )


def coordinate_generation_inputs(db: Session) -> int:
    """Recover parse outcomes and enqueue ready closed batches from durable rows."""
    now = datetime.now(UTC)
    _reconcile_missing_inputs(db)
    db.query(NotebookUploadBatch).filter(
        NotebookUploadBatch.closed_at.is_(None),
        NotebookUploadBatch.updated_at < now - BATCH_IDLE_CLOSE,
    ).update({NotebookUploadBatch.closed_at: now}, synchronize_session=False)

    rows = db.scalars(select(NotebookGenerationInput).where(
        NotebookGenerationInput.status.in_(("waiting_parse", "parsing")),
    ).order_by(NotebookGenerationInput.updated_at.desc())).all()
    for row in rows:
        if row.status == "completed":
            continue
        if row.parse_kind == "material":
            material = db.scalar(select(Material).where(Material.asset_id == row.asset_id))
            job = db.get(ProcessingJob, row.parse_job_id) if row.parse_job_id else None
            if material is not None:
                latest = db.scalar(select(ProcessingJob).where(
                    ProcessingJob.material_id == material.id,
                ).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc()).limit(1))
                if latest is not None and (job is None or latest.created_at >= job.created_at):
                    job = latest
                    row.parse_job_id = latest.id
            if job is not None and job.status in {"pending", "processing"}:
                row.status = "waiting_parse" if job.status == "pending" else "parsing"
            elif job is not None and job.status == "failed":
                row.status = "parse_failed"
                row.error_code = job.error_code or "parse_failed"
                row.error_message = job.error_message or "资料解析失败"
            else:
                fingerprint, code, message = _parse_state(db, row.asset_id)
                row.parse_result_fingerprint = fingerprint
                row.status = "ready" if fingerprint else "parse_failed"
                row.error_code = code
                row.error_message = message
        else:
            job = db.get(AssetProcessingJob, row.parse_job_id) if row.parse_job_id else None
            latest = db.scalar(select(AssetProcessingJob).where(
                AssetProcessingJob.asset_id == row.asset_id,
            ).order_by(AssetProcessingJob.created_at.desc(), AssetProcessingJob.id.desc()).limit(1))
            if latest is not None and (job is None or latest.created_at >= job.created_at):
                job = latest
                row.parse_job_id = latest.id
            if job is not None and job.status in {"pending", "processing"}:
                row.status = "waiting_parse" if job.status == "pending" else "parsing"
            elif job is not None and job.status == "failed":
                row.status = "parse_failed"
                row.error_code = job.error_code or "parse_failed"
                row.error_message = job.error_message or "图片解析失败"
            else:
                fingerprint, code, message = _parse_state(db, row.asset_id)
                row.parse_result_fingerprint = fingerprint
                row.status = "ready" if fingerprint else "parse_failed"
                row.error_code = code
                row.error_message = message
        row.updated_at = now

    db.flush()
    batches = db.scalars(select(NotebookUploadBatch).where(
        NotebookUploadBatch.closed_at.is_not(None),
        select(NotebookGenerationInput.id).where(
            NotebookGenerationInput.batch_id == NotebookUploadBatch.id,
            NotebookGenerationInput.status == "ready",
        ).exists(),
    ).order_by(NotebookUploadBatch.created_at)).all()
    enqueued = 0
    for batch in batches:
        pending_parse = db.scalar(select(NotebookGenerationInput.id).where(
            NotebookGenerationInput.batch_id == batch.id,
            NotebookGenerationInput.status.in_(("waiting_parse", "parsing")),
        ).limit(1))
        if pending_parse is not None:
            continue
        ready = db.scalars(select(NotebookGenerationInput).where(
            NotebookGenerationInput.batch_id == batch.id,
            NotebookGenerationInput.status == "ready",
        ).order_by(NotebookGenerationInput.created_at, NotebookGenerationInput.asset_id)).all()
        if not ready:
            continue
        asset_ids = [row.asset_id for row in ready]
        fingerprint = hashlib.sha256("|".join(
            f"{row.asset_id}:{row.parse_result_fingerprint}" for row in ready
        ).encode()).hexdigest()
        key = f"batch-{batch.id[:20]}-{fingerprint[:48]}"
        try:
            from app.api.v1.generation import create_generation_job
            from app.schemas.generation import NotebookGenerationCreate

            # The generation endpoint persists an immutable source snapshot.
            # The same session owns the input status updates so a successful
            # task can reconcile an interrupted link step by its source IDs.
            response = create_generation_job(
                batch.notebook_id, NotebookGenerationCreate(asset_ids=asset_ids), key, db,
            )
            task_id = response["id"]
            task = db.get(NotebookGenerationJob, task_id)
            for row in ready:
                if task and task.status in {"failed", "conflict", "cancelled", "cancel_requested"}:
                    row.status = "generation_failed"
                    row.error_code = task.error_code or task.status
                    row.error_message = task.error_message or "生成任务未完成，请重试"
                else:
                    row.status = "completed" if task and task.status == "completed" else "generating"
                    row.error_code = row.error_message = None
                row.generation_job_id = task_id
                row.retry_count += 1
                row.updated_at = now
                if row.status == "completed":
                    row.finished_at = now
            db.commit()
            enqueued += 1
        except HTTPException as exc:
            db.rollback()
            failed = db.scalars(select(NotebookGenerationInput).where(
                NotebookGenerationInput.asset_id.in_(asset_ids),
                NotebookGenerationInput.status == "ready",
            )).all()
            for row in failed:
                row.status = "parse_failed"
                row.error_code = "generation_input_rejected"
                row.error_message = str(exc.detail)[:1000]
                row.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
    db.commit()
    return enqueued
