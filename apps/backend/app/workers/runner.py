"""Single local database-backed worker; the API never executes material jobs."""

from __future__ import annotations

import os
import signal
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.migrate import migrate_database
from app.db.models import Material, ProcessingJob
from app.forest.jobs import (
    claim_next_forest_job,
    mark_interrupted_forest_jobs,
    process_forest_job,
)
from app.workers.material_worker import process_material

STOP = False
_material_jobs_since_forest = 0
FOREST_CHECK_INTERVAL = 3


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
        db.commit()
        return len(jobs)


def claim_next_job() -> str | None:
    """Atomic status transition prevents two runners from taking one pending row."""
    with SessionLocal() as db:
        candidate = db.scalar(select(ProcessingJob.id).where(
            ProcessingJob.status == "pending"
        ).order_by(ProcessingJob.created_at, ProcessingJob.id).limit(1))
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
    global _material_jobs_since_forest
    # A steady material queue must not indefinitely delay forest work.
    if _material_jobs_since_forest >= FOREST_CHECK_INTERVAL:
        forest_job_id = claim_next_forest_job()
        if forest_job_id is not None:
            _material_jobs_since_forest = 0
            process_forest_job(forest_job_id)
            return True
    job_id = claim_next_job()
    if job_id is None:
        forest_job_id = claim_next_forest_job()
        if forest_job_id is None:
            return False
        _material_jobs_since_forest = 0
        process_forest_job(forest_job_id)
        return True
    _material_jobs_since_forest += 1
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
        while not STOP:
            if not run_once():
                time.sleep(0.5)


if __name__ == "__main__":
    main()
