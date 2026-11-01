from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import Notebook, NotebookAsset, NotebookGenerationJob
from app.generation.context import GenerationInputError, build_snapshot
from app.schemas.generation import NotebookGenerationCreate
from app.workers.notebook_generation_worker import PROMPT_VERSION


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
        "processing_route": json.loads(job.input_snapshot_json).get('processing_route', 'standard'),
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


def create_generation_job(
    db: Session,
    notebook_id: str,
    payload: NotebookGenerationCreate,
    idempotency_key: str | None = None,
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
    generator = 'deepseek' if snapshot.get('processing_route') == 'llm' else settings.notebook_generator
    job = NotebookGenerationJob(
        id=new_id(), notebook_id=notebook_id, idempotency_key=key,
        request_fingerprint=request_fingerprint,
        status="pending", base_document_revision=notebook.document_revision,
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        model=(snapshot.get('provider', {}).get('model') or settings.deepseek_model) if generator == "deepseek" else generator,
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


