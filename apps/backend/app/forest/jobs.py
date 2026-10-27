"""Durable curriculum and Notebook-body relation jobs.

Legacy Note-based relation jobs remain historical records and are never claimed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.database import SessionLocal
from app.db.forest_models import CurriculumImport, ForestJob
from app.forest.curriculum import CurriculumError, extract_curriculum


def claim_next_forest_job() -> str | None:
    with SessionLocal() as db:
        job_id = db.scalar(select(ForestJob.id).where(
            ForestJob.status == "pending",
            ForestJob.kind.in_(("curriculum_import", "notebook_relations")),
        ).order_by(ForestJob.created_at, ForestJob.id).limit(1))
        if job_id is None:
            return None
        result = db.execute(update(ForestJob).where(
            ForestJob.id == job_id, ForestJob.status == "pending",
        ).values(status="processing", started_at=datetime.now(UTC),
                 heartbeat_at=datetime.now(UTC), attempt_count=ForestJob.attempt_count + 1))
        db.commit()
        return job_id if result.rowcount == 1 else None


def mark_interrupted_forest_jobs(*, force: bool = False) -> int:
    with SessionLocal() as db:
        query = select(ForestJob).where(ForestJob.status == "processing")
        if not force:
            query = query.where(ForestJob.heartbeat_at.is_(None))
        jobs = list(db.scalars(query).all())
        for job in jobs:
            job.status = "failed"
            job.error_message = "处理进程中断；可安全重试"
            job.finished_at = datetime.now(UTC)
            if job.curriculum_import_id:
                record = db.get(CurriculumImport, job.curriculum_import_id)
                if record is not None and record.status != "confirmed":
                    record.status = "failed"
                    record.error_message = job.error_message
        db.commit()
        return len(jobs)


def retry_job(db, job: ForestJob) -> ForestJob:
    if job.kind not in {"curriculum_import", "notebook_relations"}:
        raise CurriculumError("该森林任务类型已退役，请手动建立 Notebook 关系")
    if job.status not in {"failed", "pending"}:
        raise CurriculumError("只有失败的任务可以重试")
    job.status = "pending"
    job.error_message = None
    job.finished_at = None
    job.heartbeat_at = None
    job.updated_at = datetime.now(UTC)
    db.flush()
    return job


def process_forest_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(ForestJob, job_id)
        if job is None or job.status != "processing":
            return
        if job.kind == "notebook_relations":
            from app.forest.notebook_relations import process_notebook_relation_job

            db.close()
            process_notebook_relation_job(job_id)
            return
        try:
            job.progress = 10
            job.heartbeat_at = datetime.now(UTC)
            if job.kind != "curriculum_import":
                raise CurriculumError("该森林任务类型已退役")
            record = db.get(CurriculumImport, job.curriculum_import_id)
            if record is None or record.status == "confirmed":
                raise CurriculumError("培养方案已确认或不存在")
            record.status = "processing"
            db.commit()
            extract_curriculum(db, record, client=DeepSeekClient())
            job.status = "completed"
            job.progress = 100
            job.error_message = None
            job.heartbeat_at = datetime.now(UTC)
            job.finished_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ForestJob, job_id)
            if job is None:
                return
            if isinstance(exc, CurriculumError):
                message = str(exc)
            elif isinstance(exc, ValidationError):
                message = "AI 输出格式或来源校验失败，请重试并核对资料"
            elif isinstance(exc, DeepSeekError):
                message = "AI 服务调用失败，请检查模型配置或稍后重试"
            else:
                message = "森林任务处理失败；数据和原文件保留，请检查资料后重试"
            job.status = "failed"
            job.progress = 0
            job.error_message = message
            job.finished_at = datetime.now(UTC)
            if job.curriculum_import_id:
                record = db.get(CurriculumImport, job.curriculum_import_id)
                if record is not None and record.status != "confirmed":
                    record.status = "failed"
                    record.error_message = message
            db.commit()


__all__ = [
    "claim_next_forest_job",
    "mark_interrupted_forest_jobs",
    "process_forest_job",
    "retry_job",
]
