"""Generate reviewable Notebook documents without writing the live document."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.database import SessionLocal
from app.db.model_utils import new_id
from app.db.models import NotebookGenerationCandidate, NotebookGenerationJob
from app.notes.document import (
    DocumentValidationError,
    dump_document,
    normalize_document,
    validate_document,
)

PROMPT_VERSION = "notebook-document-v1"


def claim_next_generation_job() -> str | None:
    with SessionLocal() as db:
        job_id = db.scalar(select(NotebookGenerationJob.id).where(
            NotebookGenerationJob.status == "pending",
        ).order_by(NotebookGenerationJob.created_at, NotebookGenerationJob.id).limit(1))
        if job_id is None:
            return None
        result = db.execute(update(NotebookGenerationJob).where(
            NotebookGenerationJob.id == job_id,
            NotebookGenerationJob.status == "pending",
        ).values(status="processing", attempt_count=NotebookGenerationJob.attempt_count + 1,
                 updated_at=datetime.now(UTC)))
        db.commit()
        return job_id if result.rowcount == 1 else None


def process_generation_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(NotebookGenerationJob, job_id)
        if job is None or job.status != "processing":
            return
        snapshot_json = job.input_snapshot_json
    try:
        snapshot = json.loads(snapshot_json)
        result = DeepSeekClient().complete_json([
                {
                    "role": "system",
                    "content": (
                        "你为学习笔记生成一份可编辑的 Tiptap JSON v2 文档。只返回一个对象："
                        "{\"type\":\"doc\",\"content\":[...]}。仅使用允许的 heading、paragraph、"
                        "bulletList、orderedList、blockquote、codeBlock、table、callout、example、"
                        "blockMath、inlineMath 等结构。不要生成 image 节点、URL、HTML 或 SVG；"
                        "不要声称来源中没有的事实。保留当前正文中的可靠内容，并用输入资料补充解释。"
                    ),
                },
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
        ], max_tokens=6000)
        candidate = normalize_document(result.get("document", result))
        validate_document(candidate)
        error = None
    except (DeepSeekError, DocumentValidationError, ValueError, TypeError) as exc:
        candidate = None
        error = ("generation_failed", str(exc)[:1000])
    except Exception as exc:
        candidate = None
        error = ("generation_internal_error", f"生成任务失败：{type(exc).__name__}")

    with SessionLocal() as db:
        job = db.get(NotebookGenerationJob, job_id)
        if job is None:
            return
        if job.status == "cancel_requested":
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
            job.updated_at = job.finished_at
            db.commit()
            return
        if job.status != "processing":
            return
        now = datetime.now(UTC)
        if error is not None:
            job.status = "failed"
            job.error_code, job.error_message = error
        else:
            db.add(NotebookGenerationCandidate(
                id=new_id(), job_id=job.id, notebook_id=job.notebook_id,
                document_json=dump_document(candidate), status="pending_review",
                created_at=now,
            ))
            job.status = "candidate_ready"
            job.error_code = None
            job.error_message = None
        job.finished_at = now
        job.updated_at = now
        db.commit()
