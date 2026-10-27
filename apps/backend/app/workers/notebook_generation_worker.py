"""Generate and atomically append incremental Notebook document fragments."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.database import SessionLocal
from app.db.models import Notebook, NotebookGenerationInput, NotebookGenerationJob
from app.notes.document import (
    DocumentValidationError,
    dump_document,
    normalize_document,
    validate_document,
)
from app.notes.history import record_snapshot

PROMPT_VERSION = "notebook-fragment-v2"


def claim_next_generation_job() -> str | None:
    with SessionLocal() as db:
        # A notebook is a serial write stream. Do not claim its next job while
        # another generation for it is pending or processing.
        job_id = db.scalar(select(NotebookGenerationJob.id).where(
            NotebookGenerationJob.status == "pending",
            ~NotebookGenerationJob.notebook_id.in_(select(NotebookGenerationJob.notebook_id).where(
                NotebookGenerationJob.status == "processing",
            )),
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


def _generate_fragment(snapshot: dict) -> dict:
    result = DeepSeekClient().complete_json([
        {"role": "system", "content": (
            "你为学习笔记生成增量补充内容，返回 {\"type\":\"doc\",\"content\":[...]}。"
            "只生成可直接追加的新增 Tiptap JSON v2 节点，绝不重写或复制已有正文。"
            "结合已有正文概览避免重复；只依据新增资料陈述事实。仅使用项目支持的结构化节点；"
            "不要输出 image、URL、HTML 或 SVG。"
        )},
        {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
    ], max_tokens=6000)
    fragment = normalize_document(result.get("document", result))
    validate_document(fragment)
    return fragment


def process_generation_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(NotebookGenerationJob, job_id)
        if job is None or job.status != "processing":
            return
        snapshot_json = job.input_snapshot_json
    input_asset_ids: list[str] = []
    try:
        snapshot = json.loads(snapshot_json)
        input_asset_ids = [
            source["asset_id"] for source in snapshot.get("sources", [])
            if isinstance(source, dict) and isinstance(source.get("asset_id"), str)
        ]
        fragment = _generate_fragment(snapshot)
        if not fragment.get("content"):
            raise DocumentValidationError("AI 未生成可追加的文档节点")
        stack = list(fragment["content"])
        while stack:
            node = stack.pop()
            if node.get("type") == "image":
                raise DocumentValidationError("AI 生成的补充内容不能新增图片资源")
            stack.extend(node.get("content") or [])
        error = None
    except (DeepSeekError, DocumentValidationError, ValueError, TypeError) as exc:
        fragment = None
        error = ("generation_failed", str(exc)[:1000])
    except Exception as exc:
        fragment = None
        error = ("generation_internal_error", f"生成任务失败：{type(exc).__name__}")

    with SessionLocal() as db:
        job = db.get(NotebookGenerationJob, job_id)
        if job is None or job.status != "processing":
            return
        now = datetime.now(UTC)
        if error:
            job.status = "failed"
            job.error_code, job.error_message = error
            job.finished_at = job.updated_at = now
            if input_asset_ids:
                db.query(NotebookGenerationInput).filter(
                    NotebookGenerationInput.notebook_id == job.notebook_id,
                    NotebookGenerationInput.asset_id.in_(input_asset_ids),
                    NotebookGenerationInput.status != "completed",
                ).update({
                    NotebookGenerationInput.status: "generation_failed",
                    NotebookGenerationInput.generation_job_id: job.id,
                    NotebookGenerationInput.error_code: job.error_code,
                    NotebookGenerationInput.error_message: job.error_message,
                    NotebookGenerationInput.updated_at: now,
                }, synchronize_session=False)
            db.commit()
            return

        # Reload the latest document at commit time. The model sees a possibly
        # older outline, but its fragment is appended to the current root array.
        notebook = db.scalar(select(Notebook).where(
            Notebook.id == job.notebook_id, Notebook.deleted_at.is_(None),
        ))
        if notebook is None:
            job.status = "failed"
            job.error_code = "notebook_unavailable"
            job.error_message = "笔记已删除或不可用"
            job.finished_at = job.updated_at = now
            if input_asset_ids:
                db.query(NotebookGenerationInput).filter(
                    NotebookGenerationInput.notebook_id == job.notebook_id,
                    NotebookGenerationInput.asset_id.in_(input_asset_ids),
                    NotebookGenerationInput.status != "completed",
                ).update({
                    NotebookGenerationInput.status: "generation_failed",
                    NotebookGenerationInput.generation_job_id: job.id,
                    NotebookGenerationInput.error_code: job.error_code,
                    NotebookGenerationInput.error_message: job.error_message,
                    NotebookGenerationInput.updated_at: now,
                }, synchronize_session=False)
            db.commit()
            return
        from app.notes.document import load_document
        current = load_document(notebook.document_json)
        try:
            if current.warning:
                raise DocumentValidationError(current.warning)
            current_content = validate_document(current.content)
            if not isinstance(current_content.get("content"), list):
                raise DocumentValidationError("当前正文不是可安全追加的文档结构")
            used_ids: set[str] = set()
            def collect_ids(nodes):
                for node in nodes:
                    block_id = (node.get("attrs") or {}).get("blockId")
                    if isinstance(block_id, str):
                        used_ids.add(block_id)
            collect_ids(current_content.get("content") or [])
            for node in fragment["content"]:
                attrs = node.get("attrs") or {}
                block_id = attrs.get("blockId")
                if block_id in used_ids:
                    attrs["blockId"] = f"ai-{uuid.uuid4().hex[:20]}"
                    node["attrs"] = attrs
                if isinstance(attrs.get("blockId"), str):
                    used_ids.add(attrs["blockId"])
            # No AI images are accepted. Resource ownership is therefore not
            # inferred from model output; existing references remain untouched.
            appended = {"type": "doc", "content": [*current_content["content"], *fragment["content"]]}
            appended = validate_document(appended)
        except (DocumentValidationError, KeyError, TypeError) as exc:
            job.status = "failed"
            job.error_code = "document_validation_failed"
            job.error_message = str(exc)[:1000]
            job.finished_at = job.updated_at = now
            if input_asset_ids:
                db.query(NotebookGenerationInput).filter(
                    NotebookGenerationInput.notebook_id == job.notebook_id,
                    NotebookGenerationInput.asset_id.in_(input_asset_ids),
                    NotebookGenerationInput.status != "completed",
                ).update({
                    NotebookGenerationInput.status: "generation_failed",
                    NotebookGenerationInput.generation_job_id: job.id,
                    NotebookGenerationInput.error_code: job.error_code,
                    NotebookGenerationInput.error_message: job.error_message,
                    NotebookGenerationInput.updated_at: now,
                }, synchronize_session=False)
            db.commit()
            return

        base_revision = notebook.document_revision
        next_revision = base_revision + 1
        changed = db.execute(update(Notebook).where(
            Notebook.id == notebook.id,
            Notebook.document_revision == base_revision,
            Notebook.deleted_at.is_(None),
        ).values(document_json=dump_document(appended), document_revision=next_revision, updated_at=now))
        if changed.rowcount != 1:
            db.rollback()
            # Keep the generated fragment as durable job input for retry; the
            # retry re-reads and appends to the newest正文.
            with SessionLocal() as retry_db:
                retry_job = retry_db.get(NotebookGenerationJob, job_id)
                if retry_job and retry_job.status == "processing":
                    retry_job.status = "failed" if retry_job.attempt_count >= 3 else "pending"
                    retry_job.error_code = "revision_conflict"
                    retry_job.error_message = (
                        "正文连续并发更新，自动重试次数已用尽；请手动重试生成"
                        if retry_job.status == "failed" else "正文并发更新，已排队重试追加"
                    )
                    if retry_job.status == "failed":
                        retry_job.finished_at = now
                    else:
                        latest_notebook = retry_db.get(Notebook, retry_job.notebook_id)
                        if latest_notebook is not None and latest_notebook.deleted_at is None:
                            latest_document = load_document(latest_notebook.document_json)
                            latest_snapshot = json.loads(retry_job.input_snapshot_json)
                            latest_snapshot["base_document_revision"] = latest_notebook.document_revision
                            latest_snapshot["current_document"] = latest_document.content
                            retry_job.base_document_revision = latest_notebook.document_revision
                            retry_job.input_snapshot_json = json.dumps(
                                latest_snapshot, ensure_ascii=False,
                            )
                    retry_job.updated_at = now
                    if retry_job.status == "failed" and input_asset_ids:
                        retry_db.query(NotebookGenerationInput).filter(
                            NotebookGenerationInput.notebook_id == retry_job.notebook_id,
                            NotebookGenerationInput.asset_id.in_(input_asset_ids),
                            NotebookGenerationInput.status == "generating",
                        ).update({
                            NotebookGenerationInput.status: "generation_failed",
                            NotebookGenerationInput.error_code: retry_job.error_code,
                            NotebookGenerationInput.error_message: retry_job.error_message,
                            NotebookGenerationInput.updated_at: now,
                        }, synchronize_session=False)
                    retry_db.commit()
            return
        record_snapshot(db, notebook.id, next_revision, appended, origin="ai_append")
        if input_asset_ids:
            db.query(NotebookGenerationInput).filter(
                NotebookGenerationInput.notebook_id == job.notebook_id,
                NotebookGenerationInput.asset_id.in_(input_asset_ids),
                NotebookGenerationInput.status != "completed",
            ).update({
                NotebookGenerationInput.status: "completed",
                NotebookGenerationInput.generation_job_id: job.id,
                NotebookGenerationInput.error_code: None,
                NotebookGenerationInput.error_message: None,
                NotebookGenerationInput.updated_at: now,
                NotebookGenerationInput.finished_at: now,
            }, synchronize_session=False)
        job.status = "completed"
        job.base_document_revision = base_revision
        job.error_code = job.error_message = None
        job.finished_at = job.updated_at = now
        db.commit()
