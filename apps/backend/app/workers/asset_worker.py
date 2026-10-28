"""Background processing for image Assets through the unified Document pipeline."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.database import SessionLocal
from app.db.models import Asset, AssetProcessingJob
from app.document_processing.service import (
    DocumentProcessingError,
    create_parse_run,
    execute_parse_run,
    fail_parse_run,
    load_ir,
)
from app.notes.assets import AssetUnavailable, storage_path


def claim_next_asset_job() -> str | None:
    with SessionLocal() as db:
        job_id = db.scalar(select(AssetProcessingJob.id).where(
            AssetProcessingJob.status == "pending",
        ).order_by(AssetProcessingJob.created_at, AssetProcessingJob.id).limit(1))
        if job_id is None:
            return None
        result = db.execute(update(AssetProcessingJob).where(
            AssetProcessingJob.id == job_id,
            AssetProcessingJob.status == "pending",
        ).values(status="processing", attempt_count=AssetProcessingJob.attempt_count + 1,
                 updated_at=datetime.now(UTC)))
        db.commit()
        return job_id if result.rowcount == 1 else None


def process_asset_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(AssetProcessingJob, job_id)
        if job is None or job.status != "processing":
            return
        asset = db.get(Asset, job.asset_id)
        run_id: str | None = None
        try:
            if asset is None or asset.state != "ready":
                raise DocumentProcessingError(
                    "原始图片资源当前不可用", code="asset_unavailable",
                )
            try:
                source_path = storage_path(asset)
            except AssetUnavailable as exc:
                raise DocumentProcessingError(str(exc), code="asset_missing") from exc

            run = create_parse_run(db, asset=asset, reparse=job.kind == "image_reparse")
            db.commit()
            if run.status == "completed":
                quality = load_ir(db, run).quality
            else:
                run_id = run.id
                outcome = execute_parse_run(db, run.id, source_path=source_path,
                                            title=asset.original_name)
                quality = outcome.ir.quality
            job.error_code = None
            job.error_message = None
            if quality.status in {"complete", "partial"} and quality.generation_allowed:
                job.status = "completed"
            elif quality.status in {"needs_ocr", "needs_vision", "partial"}:
                job.status = "completed_with_warnings"
                job.error_code = (
                    "ocr_unavailable" if quality.status == "needs_ocr"
                    else "vision_unavailable" if quality.status == "needs_vision"
                    else "parse_quality_partial"
                )
                job.error_message = quality.generation_block_reason or "图片解析不完整，可人工核对"
            else:
                job.status = "failed"
                job.error_code = "parse_quality_insufficient"
                job.error_message = quality.generation_block_reason or "图片没有可用内容"
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(AssetProcessingJob, job_id)
            if job is None:
                return
            code = exc.code if isinstance(exc, DocumentProcessingError) else "image_parse_failed"
            message = str(exc) or type(exc).__name__
            if run_id:
                try:
                    fail_parse_run(db, run_id, code=code, message=message)
                except Exception:  # pragma: no cover
                    db.rollback()
            job.status = "failed"
            job.error_code = code
            job.error_message = message[:2000]
            db.commit()
        finally:
            job = db.get(AssetProcessingJob, job_id)
            if job is not None:
                job.finished_at = datetime.now(UTC)
                job.updated_at = job.finished_at
                db.commit()
