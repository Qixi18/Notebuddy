"""Durable automatic links between current Notebook body sections."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.database import SessionLocal
from app.db.models import Course, ForestJob, Notebook, NotebookRelation
from app.forest.relation_candidates import candidate_snapshots, snapshot_fingerprint
from app.forest.service import relation_anchor_fingerprint


class RelationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str
    target_key: str
    relation_type: Literal["related", "prerequisite", "application"]
    reason: str = Field(min_length=1, max_length=4000)


class RelationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relations: list[RelationProposal] = Field(max_length=30)


def enqueue_notebook_relations(db, course_id: str, *, notebook_id: str | None = None):
    snapshot = candidate_snapshots(db, course_id, notebook_id=notebook_id)
    if not snapshot["sources"] or not snapshot["targets"]:
        return None
    key = f"notebook-relations:{course_id}:{snapshot_fingerprint(snapshot)}"
    now = datetime.now(UTC)
    db.execute(insert(ForestJob).values(
        kind="notebook_relations", course_id=course_id, status="pending", progress=0,
        idempotency_key=key, source_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        created_at=now, updated_at=now,
    ).on_conflict_do_nothing(index_elements=[ForestJob.idempotency_key]))
    return db.scalar(select(ForestJob).where(ForestJob.idempotency_key == key))


def process_notebook_relation_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(ForestJob, job_id)
        if job is None or job.kind != "notebook_relations" or job.status != "processing":
            return
        attempt = job.attempt_count
        try:
            snapshot = json.loads(job.source_snapshot_json)
            client = DeepSeekClient()
            if not client.configured:
                raise DeepSeekError("模型未配置，请配置后重试")
            # Release the SQLite read transaction before contacting the model.
            db.commit()
            result = client.complete_json([
                {"role": "system", "content": (
                    "依据给定笔记正文片段判断跨课联系。只输出 JSON："
                    '{"relations":[{"source_key":"s0","target_key":"t0",'
                    '"relation_type":"related|prerequisite|application","reason":"具体中文依据"}]}。'
                    "只选择输入已有的 source/target key；不得编造引用或知识点。"
                    "仅标题相似而缺乏正文支持时不要连接。证据不足返回空 relations。"
                    "这是模型推断关系，依据必须说明两端正文如何联系。"
                )},
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
            ], max_tokens=4000)
            output = RelationOutput.model_validate(result)
            guarded = db.execute(update(ForestJob).where(
                ForestJob.id == job_id, ForestJob.status == "processing",
                ForestJob.attempt_count == attempt,
            ).values(heartbeat_at=datetime.now(UTC)).execution_options(synchronize_session=False))
            if guarded.rowcount != 1:
                db.rollback()
                return
            sources = {row["key"]: row for row in snapshot["sources"]}
            targets = {row["key"]: row for row in snapshot["targets"]}
            for proposal in output.relations:
                source = sources.get(proposal.source_key)
                target = targets.get(proposal.target_key)
                if source is None or target is None or not proposal.reason.strip():
                    raise ValueError("模型引用了输入之外的小节或没有提供依据")
                for endpoint in (source, target):
                    book = db.get(Notebook, endpoint["notebook_id"], populate_existing=True)
                    course = db.get(Course, endpoint["course_id"], populate_existing=True)
                    if (book is None or book.deleted_at is not None
                            or book.course_id != endpoint["course_id"]
                            or course is None or course.deleted_at is not None
                            or relation_anchor_fingerprint(book, endpoint["block_id"]) != endpoint["fingerprint"]):
                        raise ValueError("关联依据的正文或课程归属已变化，请基于当前正文重新生成")
                existing = db.scalar(select(NotebookRelation).where(
                    NotebookRelation.source_notebook_id == source["notebook_id"],
                    NotebookRelation.target_notebook_id == target["notebook_id"],
                    NotebookRelation.source_block_id == source["block_id"],
                    NotebookRelation.target_block_id == target["block_id"],
                    NotebookRelation.relation_type == proposal.relation_type,
                ))
                if existing is not None and existing.origin != "ai":
                    continue
                relation = existing or NotebookRelation(
                    source_notebook_id=source["notebook_id"], target_notebook_id=target["notebook_id"],
                    source_block_id=source["block_id"], target_block_id=target["block_id"],
                    relation_type=proposal.relation_type, origin="ai",
                )
                relation.source_fingerprint = source["fingerprint"]
                relation.target_fingerprint = target["fingerprint"]
                relation.description = proposal.reason.strip()
                db.add(relation)
                db.flush()
            job.status = "completed"
            job.progress = 100
            job.completed_source_count = len(sources)
            job.error_message = None
            job.finished_at = job.updated_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:
            db.rollback()
            if isinstance(exc, (DeepSeekError, ValueError, ValidationError)):
                message = str(exc)[:1000]
            else:
                message = f"Notebook 关联生成失败：{type(exc).__name__}，可安全重试"
            db.execute(update(ForestJob).where(
                ForestJob.id == job_id, ForestJob.status == "processing",
                ForestJob.attempt_count == attempt,
            ).values(status="failed", error_message=message,
                     finished_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
            db.commit()
