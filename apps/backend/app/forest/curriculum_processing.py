"""Frozen curriculum routes and successful, bounded model steps."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.db.models import ForestJob
from app.document_processing.checkpoints import WorkPending, fingerprint, get_step, put_step
from app.document_processing.config import provider_client, provider_snapshot
from app.services.provider_audit import (
    begin_call,
    estimate_token_cost,
    finish_call,
    provider_status_from_error,
)


class CurriculumProcessingError(ValueError):
    """Only controlled, actionable messages are exposed by the worker."""


def latest_job(db, record):
    return db.scalar(select(ForestJob).where(ForestJob.curriculum_import_id == record.id)
                     .order_by(ForestJob.created_at.desc(), ForestJob.id).limit(1))


def job_snapshot(job) -> dict:
    try:
        value = json.loads(job.source_snapshot_json) if job else {}
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def source_path(record):
    from pathlib import Path

    name = record.stored_filename
    if not name or Path(name).name != name:
        raise CurriculumProcessingError("培养方案原文件路径无效，请重新导入")
    path = settings.originals_dir / name
    if not path.is_file():
        raise CurriculumProcessingError("培养方案原文件不存在，请重新导入")
    return path


def source_hash(record) -> str:
    if record.stored_filename:
        with source_path(record).open('rb') as source:
            return hashlib.file_digest(source, 'sha256').hexdigest()
    return hashlib.sha256(record.input_text.encode('utf-8')).hexdigest()


def new_snapshot(record, route: str) -> dict:
    return {'version': 1, 'processing_route': route, 'provider': provider_snapshot(),
            'source_sha256': source_hash(record)}


class CurriculumRun:
    def __init__(self, db, record, *, client=None, max_new_steps=None):
        self.db, self.record = db, record
        self.job = latest_job(db, record)
        self.snapshot = job_snapshot(self.job)
        if 'processing_route' not in self.snapshot:
            self.snapshot = new_snapshot(record, 'standard')
            if self.job:
                self.job.source_snapshot_json = json.dumps(self.snapshot, ensure_ascii=False)
                db.commit()
        if source_hash(record) != self.snapshot.get('source_sha256'):
            raise CurriculumProcessingError("培养方案原文件或文本已变化，请重新导入以保留可核对来源")
        self.route = self.snapshot['processing_route']
        self.client = client if client is not None else provider_client(self.snapshot.get('provider', {}))
        self.limit, self.used = max_new_steps, 0
        if self.route == 'llm' and not self.client.configured:
            raise CurriculumProcessingError("全程 AI 需要配置模型服务，请在设置中配置后重试")

    def progress(self, value: int, phase: str):
        if self.job:
            self.job.progress = max(self.job.progress, min(99, value))
            self.job.heartbeat_at = datetime.now(UTC)
            self.snapshot['phase'] = phase
            self.job.source_snapshot_json = json.dumps(self.snapshot, ensure_ascii=False)
            self.db.commit()

    def step(self, stage, key, identity, call, validate):
        digest = fingerprint([self.route, self.snapshot.get('provider'), stage, key, identity])
        scope = f'curriculum:{self.record.id}'
        cached = get_step(self.db, scope, stage, key, digest)
        if cached is not None:
            return validate(cached)
        if self.limit is not None and self.used >= self.limit:
            raise WorkPending()
        audit, started = begin_call(self.db, provider='deepseek', operation='curriculum_import',
            model=self.snapshot.get('provider', {}).get('model'),
            metadata={'route': self.route, 'stage': stage, 'step': key})
        self.db.commit()
        try:
            result = validate(call())
        except Exception as exc:
            finish_call(self.db, audit, started, status=provider_status_from_error(exc),
                        error_type=type(exc).__name__)
            self.db.commit()
            raise
        usage = getattr(self.client, 'last_usage', None)
        finish_call(self.db, audit, started, status='success',
            request_units=(usage or {}).get('prompt_tokens'),
            response_units=(usage or {}).get('completion_tokens'),
            estimated_cost_usd=estimate_token_cost(usage,
                input_rate_per_million=settings.deepseek_input_cost_per_million,
                output_rate_per_million=settings.deepseek_output_cost_per_million))
        put_step(self.db, scope, stage, key, digest, result, usage)
        self.used += 1
        return result
