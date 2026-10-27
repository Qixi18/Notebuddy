"""Material parse worker: one Document Processing pipeline, no legacy body writes.

The worker no longer performs course-scoped knowledge extraction, web-search
annotations or legacy retrieval indexing.  It creates a versioned ParseRun,
stores Document IR evidence and quality, and leaves generation to the Notebook
generation worker (which reads the current ParseRun).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Asset, Material, ProcessingJob
from app.document_processing.service import (
    DocumentProcessingError,
    create_parse_run,
    execute_parse_run,
    fail_parse_run,
)
from app.notes.assets import AssetUnavailable, storage_path


def process_material(job_id: str) -> None:
    db = SessionLocal()
    job = None
    run_id: str | None = None
    try:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status != "processing":
            return
        material = job.material
        job.status = "processing"
        job.phase = "parse"
        job.web_search_status = "unavailable"
        job.progress = 5
        job.heartbeat_at = datetime.now(UTC)
        material.status = "processing"
        db.commit()

        asset = _resolve_asset(db, material)
        if asset is None:
            raise DocumentProcessingError(
                "资料缺少统一资源记录（Asset），请重新上传该文件", code="asset_missing",
            )
        if asset.state != "ready":
            raise DocumentProcessingError(
                f"原始文件当前不可读（{asset.state}），请重新上传", code="asset_unavailable",
            )
        try:
            source_path = storage_path(asset)
        except AssetUnavailable as exc:
            raise DocumentProcessingError(str(exc), code="asset_missing") from exc

        reparse = job.kind in {"reparse_material", "ocr_material"}
        run = create_parse_run(db, asset=asset, reparse=reparse)
        run_id = run.id
        job.progress = 10
        job.heartbeat_at = datetime.now(UTC)
        db.commit()

        outcome = execute_parse_run(
            db, run.id, source_path=source_path, title=material.lecture_title,
        )
        quality = outcome.ir.quality

        material.parser_version = outcome.run.parser_version
        material.page_count = outcome.run.page_count
        material.document_warning = _quality_warning(quality)
        material.status = "completed"

        job.status = "completed"
        job.phase = "completed"
        job.progress = 100
        job.error_code = None if quality.generation_allowed else "parse_quality_insufficient"
        job.error_message = None if quality.generation_allowed else quality.generation_block_reason
        job.finished_at = datetime.now(UTC)
        job.heartbeat_at = job.finished_at
        db.commit()
    except Exception as exc:
        db.rollback()
        if job is None:
            job = db.get(ProcessingJob, job_id)
        code = exc.code if isinstance(exc, DocumentProcessingError) else "processing_failed"
        message = str(exc) or type(exc).__name__
        if run_id:
            try:
                fail_parse_run(db, run_id, code=code, message=message)
            except Exception:  # pragma: no cover - failure bookkeeping only
                db.rollback()
        if job is None:
            return
        job.status = "failed"
        job.phase = "failed"
        job.error_code = code
        job.error_message = message[:2000]
        job.progress = 0
        job.finished_at = datetime.now(UTC)
        job.heartbeat_at = job.finished_at
        if job.material is not None:
            job.material.status = "failed"
            job.material.document_warning = message[:2000]
        db.commit()
    finally:
        db.close()


def _resolve_asset(db, material: Material) -> Asset | None:
    if material.asset_id:
        asset = db.get(Asset, material.asset_id)
        if asset is not None:
            return asset
    asset = db.get(Asset, material.id)
    if asset is not None:
        return asset
    if material.stored_filename:
        return db.scalar(select(Asset).where(
            Asset.storage_key == f"originals/{material.stored_filename}",
        ))
    return None


def _quality_warning(quality) -> str | None:
    if quality.generation_allowed and quality.status == "complete":
        return None
    parts = [issue.message for issue in quality.issues if issue.severity in {"blocking", "warning"}]
    reason = quality.generation_block_reason
    if reason:
        parts.insert(0, reason)
    return "；".join(dict.fromkeys(part for part in parts if part))[:2000] or None
