"""Successful model steps, scoped and fingerprinted independently of retries."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.db.models import ProcessingStep, new_id, utc_now

MAX_STRUCTURED_OUTPUT_TOKENS = 32_000


class WorkPending(Exception):
    """Yield a durable model task between bounded batches."""


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def get_step(db, scope: str, stage: str, key: str, identity: str):
    row = db.scalar(select(ProcessingStep).where(
        ProcessingStep.scope == scope, ProcessingStep.stage == stage,
        ProcessingStep.step_key == key, ProcessingStep.fingerprint == identity))
    return json.loads(row.result_json) if row else None


def put_step(db, scope: str, stage: str, key: str, identity: str, result, usage=None):
    db.execute(insert(ProcessingStep).values(
        id=new_id(), scope=scope, stage=stage, step_key=key, fingerprint=identity,
        result_json=json.dumps(result, ensure_ascii=False),
        usage_json=json.dumps(usage) if usage else None, created_at=utc_now(),
    ).on_conflict_do_nothing(index_elements=['scope', 'stage', 'step_key', 'fingerprint']))
    db.commit()


def structured_call(client, messages, *, max_tokens=8000):
    """Bound retries and grow truncated output budgets; never retry auth/credit errors."""
    import time

    from app.ai.deepseek import DeepSeekError
    budget = max_tokens
    for attempt in range(3):
        try:
            result = client.complete_json(messages, max_tokens=budget)
            if client.last_finish_reason == 'length':
                raise DeepSeekError('模型输出被截断，请减小批次后重试', code='output_truncated')
            return result
        except DeepSeekError as exc:
            truncated = (exc.code == 'output_truncated'
                         or (exc.code == 'invalid_json' and client.last_finish_reason == 'length'))
            if truncated:
                expanded = min(MAX_STRUCTURED_OUTPUT_TOKENS, budget * 2)
                if attempt == 2 or expanded <= budget:
                    raise
                budget = expanded
                continue
            transient = (exc.status_code in {408, 429, 500, 502, 503, 504}
                         or exc.code in {'provider_transport', 'provider_empty'})
            if not transient or attempt == 2:
                raise
            time.sleep(min(10.0, exc.retry_after or 2 ** attempt))
