"""Single local database-backed worker; the API never executes material jobs."""

from __future__ import annotations

import logging
import os
import signal
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.migrate import migrate_database
from app.db.models import (
    Asset,
    AssetProcessingJob,
    Material,
    NotebookGenerationInput,
    NotebookGenerationJob,
    ProcessingJob,
)
from app.forest.jobs import (
    claim_next_forest_job,
    mark_interrupted_forest_jobs,
    process_forest_job,
)
from app.notes.assets import collect_detached_assets
from app.notes.attachments import (
    prune_deleted_notebook_directories,
    prune_stray_attachment_files,
    prune_unreferenced_attachments,
)
from app.services.image_assets import reconcile_staged_images
from app.services.notebook_generation_inputs import coordinate_generation_inputs
from app.services.uploads import reconcile_staged_document_assets
from app.workers.asset_worker import claim_next_asset_job, process_asset_job
from app.workers.material_worker import process_material
from app.workers.notebook_generation_worker import (
    claim_next_generation_job,
    process_generation_job,
)

STOP = False
ATTACHMENT_CLEANUP_INTERVAL = 60 * 60
logger = logging.getLogger(__name__)
_material_jobs_since_forest = 0
_material_jobs_since_asset = 0
_jobs_since_generation = 0
FOREST_CHECK_INTERVAL = 3
GENERATION_COORDINATION_INTERVAL = 1.0
_last_generation_coordination = 0.0


def _stop(*_: object) -> None:
    global STOP
    STOP = True


def mark_interrupted_jobs(*, force: bool = False) -> int:
    """Do not silently replay a partly committed job after its owner disappears."""
    with SessionLocal() as db:
        query = select(ProcessingJob).where(ProcessingJob.status == "processing")
        if not force:
            query = query.where(ProcessingJob.heartbeat_at.is_(None))
        jobs = list(db.scalars(query).all())
        for job in jobs:
            job.status = "failed"
            job.phase = "failed"
            job.error_code = "interrupted"
            job.error_message = "处理进程中断；原文件仍保留，可重试"
            job.finished_at = datetime.now(UTC)
            material = db.get(Material, job.material_id)
            if material is not None:
                material.status = "failed"
        image_jobs = db.scalars(select(AssetProcessingJob).where(
            AssetProcessingJob.status == "processing",
        )).all()
        for job in image_jobs:
            job.status = "failed"
            job.error_code = "interrupted"
            job.error_message = "图片解析进程中断；原图仍保留，可重试"
            job.finished_at = datetime.now(UTC)
            job.updated_at = job.finished_at
        generation_jobs = db.scalars(select(NotebookGenerationJob).where(
            NotebookGenerationJob.status.in_(("processing", "cancel_requested")),
        )).all()
        for job in generation_jobs:
            cancelled = job.status == "cancel_requested"
            job.status = "cancelled" if cancelled else "failed"
            job.error_code = "cancelled" if cancelled else "interrupted"
            job.error_message = "生成已取消" if cancelled else "生成进程中断；可使用相同输入重新尝试"
            job.finished_at = datetime.now(UTC)
            job.updated_at = job.finished_at
            db.query(NotebookGenerationInput).filter(
                NotebookGenerationInput.generation_job_id == job.id,
                NotebookGenerationInput.status == "generating",
            ).update({
                NotebookGenerationInput.status: "generation_failed",
                NotebookGenerationInput.error_code: job.error_code,
                NotebookGenerationInput.error_message: job.error_message,
                NotebookGenerationInput.updated_at: job.finished_at,
            }, synchronize_session=False)
        db.commit()
        return len(jobs)


def claim_next_job() -> str | None:
    """Atomic status transition prevents two runners from taking one pending row."""
    with SessionLocal() as db:
        candidate = db.scalar(select(ProcessingJob.id).where(
            ProcessingJob.status == "pending",
        ).join(Material, Material.id == ProcessingJob.material_id)
          .outerjoin(Asset, Asset.id == Material.asset_id)
          .where(or_(Material.asset_id.is_(None), Asset.state == "ready"))
          .order_by(ProcessingJob.updated_at, ProcessingJob.created_at, ProcessingJob.id).limit(1))
        if candidate is None:
            return None
        now = datetime.now(UTC)
        claimed = db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == candidate, ProcessingJob.status == "pending")
            .values(
                status="processing", phase="parse", started_at=now,
                heartbeat_at=now, attempt_count=ProcessingJob.attempt_count + 1,
            )
        )
        db.commit()
        return candidate if claimed.rowcount == 1 else None


def run_once() -> bool:
    global _material_jobs_since_forest, _material_jobs_since_asset, _jobs_since_generation
    global _last_generation_coordination
    now = time.monotonic()
    if now - _last_generation_coordination >= GENERATION_COORDINATION_INTERVAL:
        try:
            with SessionLocal() as db:
                coordinate_generation_inputs(db)
        except Exception:
            logger.exception("Notebook generation input coordination failed")
        _last_generation_coordination = now
    if _jobs_since_generation >= 3:
        generation_id = claim_next_generation_job()
        if generation_id is not None:
            _jobs_since_generation = 0
            process_generation_job(generation_id)
            return True
    if _material_jobs_since_asset >= 3:
        asset_job_id = claim_next_asset_job()
        if asset_job_id is not None:
            _material_jobs_since_asset = 0
            process_asset_job(asset_job_id)
            return True
    # A steady material queue must not indefinitely delay forest work.
    if _material_jobs_since_forest >= FOREST_CHECK_INTERVAL:
        forest_job_id = claim_next_forest_job()
        if forest_job_id is not None:
            _material_jobs_since_forest = 0
            process_forest_job(forest_job_id)
            return True
    job_id = claim_next_job()
    if job_id is None:
        asset_job_id = claim_next_asset_job()
        if asset_job_id is not None:
            _material_jobs_since_asset = 0
            process_asset_job(asset_job_id)
            return True
        generation_id = claim_next_generation_job()
        if generation_id is not None:
            _jobs_since_generation = 0
            process_generation_job(generation_id)
            return True
        forest_job_id = claim_next_forest_job()
        if forest_job_id is None:
            return False
        _material_jobs_since_forest = 0
        process_forest_job(forest_job_id)
        return True
    _material_jobs_since_forest += 1
    _material_jobs_since_asset += 1
    _jobs_since_generation += 1
    process_material(job_id)
    return True


@contextmanager
def exclusive_runner_lock(path: Path):
    """An OS lock prevents a second runner from treating a live job as interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Material worker is already running") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Material worker is already running") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def main() -> None:
    migrate_database()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    with exclusive_runner_lock(settings.data_dir / "worker.lock"):
        mark_interrupted_jobs(force=True)
        mark_interrupted_forest_jobs(force=True)
        next_attachment_cleanup = 0.0
        while not STOP:
            if time.monotonic() >= next_attachment_cleanup:
                try:
                    with SessionLocal() as db:
                        reconcile_staged_images(db)
                        reconcile_staged_document_assets(db)
                        collect_detached_assets(db)
                        prune_unreferenced_attachments(db)
                        prune_deleted_notebook_directories(db)
                        prune_stray_attachment_files(db)
                except Exception:
                    logger.exception("Notebook attachment cleanup failed")
                next_attachment_cleanup = time.monotonic() + ATTACHMENT_CLEANUP_INTERVAL
            if not run_once():
                time.sleep(0.5)


if __name__ == "__main__":
    main()
