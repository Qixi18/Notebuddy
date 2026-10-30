"""Generate a Notebook fragment from Document IR and merge it safely.

Pipeline: persisted plan -> batched composition -> schema/source validation ->
append-only merge with revision CAS -> source relations -> derived index.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import (
    DocumentBlock,
    DocumentPage,
    DocumentParseRun,
    Notebook,
    NotebookAsset,
    NotebookBlockSource,
    NotebookGenerationInput,
    NotebookGenerationJob,
)
from app.document_processing.checkpoints import (
    WorkPending,
    fingerprint,
    get_step,
    put_step,
    structured_call,
)
from app.document_processing.routes import provider_client
from app.generation.composer import CompositionError, compose
from app.generation.context import GenerationInputError, current_outline
from app.generation.figures import append_source_figures
from app.generation.llm_planner import build_llm_plan
from app.generation.planner import build_plan
from app.generation.resume import compose_batch
from app.notes.document import (
    DocumentValidationError,
    load_document,
    normalize_document,
    validate_document,
)
from app.notes.store import DocumentConflict, body_fingerprint, write_document
from app.services.notebook_generation_inputs import cancel_generation_inputs

PROMPT_VERSION = "notebook-generation-v3"


def claim_next_generation_job() -> str | None:
    with SessionLocal() as db:
        # A notebook is a serial write stream. Do not claim its next job while
        # another generation for it is pending or processing.
        busy = aliased(NotebookGenerationJob)
        available = ~select(busy.id).where(
            busy.notebook_id == NotebookGenerationJob.notebook_id,
            or_(busy.status.in_(("processing", "cancel_requested")),
                and_(busy.status == 'pending', or_(
                    busy.created_at < NotebookGenerationJob.created_at,
                    and_(busy.created_at == NotebookGenerationJob.created_at,
                         busy.id < NotebookGenerationJob.id)))),
        ).exists()
        job_id = db.scalar(select(NotebookGenerationJob.id).where(
            NotebookGenerationJob.status == "pending",
            available,
        ).order_by(NotebookGenerationJob.updated_at, NotebookGenerationJob.created_at, NotebookGenerationJob.id).limit(1))
        if job_id is None:
            return None
        result = db.execute(update(NotebookGenerationJob).where(
            NotebookGenerationJob.id == job_id,
            NotebookGenerationJob.status == "pending",
            # Recheck in the write statement: another runner may have claimed
            # a different job for the same Notebook after our SELECT.
            available,
        ).values(status="processing", attempt_count=NotebookGenerationJob.attempt_count + 1,
                 updated_at=datetime.now(UTC)))
        db.commit()
        return job_id if result.rowcount == 1 else None


def process_generation_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(NotebookGenerationJob, job_id)
        if job is None:
            return
        attempt = job.attempt_count
        if not _checkpoint(db, job, attempt):
            return
        snapshot = _parse_json(job.input_snapshot_json) or {}
        llm_route = snapshot.get('processing_route') == 'llm'
        model_steps = 0
        def cached_model_call(messages, *, max_tokens=6000, validator=None):
            nonlocal model_steps
            identity = fingerprint([messages, snapshot.get('provider'), 'plan-v1'])
            cached = get_step(db, job.id, 'plan', identity, identity)
            if cached is not None:
                if validator:
                    validator(cached)
                return cached
            if model_steps >= 2:
                raise WorkPending()
            if not _checkpoint(db, job, attempt):
                raise CompositionError('任务已停止', code='cancelled')
            db.commit()
            client = provider_client(snapshot.get('provider', {}))
            result = structured_call(client, messages, max_tokens=max_tokens)
            if validator:
                validator(result)
            if not _checkpoint(db, job, attempt):
                raise CompositionError('任务已停止', code='cancelled')
            put_step(db, job.id, 'plan', identity, identity, result, client.last_usage)
            model_steps += 1
            return result
        try:
            _validate_snapshot_sources(db, job.notebook_id, snapshot)
        except GenerationInputError as exc:
            _fail_inputs(db, job, exc.code, str(exc), attempt)
            return
        plan = _parse_json(job.knowledge_plan_json) if job.knowledge_plan_json else None
        if plan is None:
            if not _guard_processing(db, job.id, attempt):
                db.rollback()
                _checkpoint(db, job, attempt)
                return
            notebook = db.get(Notebook, job.notebook_id, populate_existing=True)
            if notebook is None or notebook.deleted_at is not None:
                _fail_inputs(db, job, "notebook_unavailable", "笔记已删除或不可用", attempt)
                return
            stored = load_document(notebook.document_json)
            if stored.warning:
                _fail_inputs(db, job, "document_validation_failed", stored.warning, attempt)
                return
            # Queued jobs may start after another append or history restore.
            # Preserve source versions, but plan against the current body and
            # retain the enqueue revision for audit.
            snapshot.setdefault("initial_base_document_revision", job.base_document_revision)
            snapshot["base_document_revision"] = notebook.document_revision
            snapshot["current_document"] = stored.content
            snapshot["current_outline"] = current_outline(stored.content)
            snapshot["consumed_parse_run_ids"] = _consumed_parse_runs(db, job.notebook_id)
            job.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            job.base_document_revision = notebook.document_revision
            try:
                plan = build_llm_plan(snapshot, cached_model_call) if llm_route else build_plan(snapshot)
            except WorkPending:
                job.status = 'pending'
                job.updated_at = datetime.now(UTC)
                db.commit()
                return
            except Exception as exc:
                _fail_inputs(db, job, "plan_failed", f"生成计划构建失败：{exc}", attempt)
                return
            job.knowledge_plan_json = json.dumps(plan, ensure_ascii=False)
            job.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            db.commit()
        generator = job.generator or settings.notebook_generator
        try:
            compositions = []
            def fresh_composition(snapshot, plan, batch, *, generator):
                nonlocal model_steps
                if model_steps >= 2:
                    raise WorkPending()
                result = compose(snapshot, plan, batch, generator=generator)
                result.nodes = _normalize_model_blocks(result.nodes)
                if not _checkpoint(db, job, attempt):
                    raise CompositionError('任务已停止', code='cancelled')
                model_steps += 1
                return result
            for batch in plan.get("batches") or []:
                if not _checkpoint(db, job, attempt):
                    return
                # Do not hold a read transaction across a network/model call.
                db.commit()
                if llm_route:
                    compositions.append(compose_batch(db, job.id, snapshot, plan, batch, generator,
                                                       compose_impl=fresh_composition))
                else:
                    compositions.append(compose(snapshot, plan, batch, generator=generator))
                if not _checkpoint(db, job, attempt):
                    return
        except WorkPending:
            job.status = 'pending'
            job.updated_at = datetime.now(UTC)
            db.commit()
            return
        except DocumentValidationError as exc:
            _fail_inputs(db, job, 'document_validation_failed', str(exc), attempt)
            return
        except (CompositionError, GenerationInputError) as exc:
            _fail_inputs(db, job, getattr(exc, "code", "generation_failed"), str(exc), attempt)
            return
        except Exception as exc:  # provider boundary; keep the job retryable
            _fail_inputs(db, job, "generation_internal_error",
                         f"生成任务失败：{type(exc).__name__}", attempt)
            return

        nodes: list[dict[str, Any]] = []
        source_map: dict[str, list[str]] = {}
        for composition in compositions:
            nodes.extend(composition.nodes)
            for block_id, ids in composition.source_map.items():
                source_map[block_id] = list(dict.fromkeys(source_map.get(block_id, []) + ids))
        if not nodes:
            if plan.get("units") and all(
                unit.get("intent") == "skip" for unit in plan["units"]
            ):
                _complete_without_append(db, job, attempt)
                return
            _fail_inputs(db, job, "empty_generation", "没有可追加的正文内容（资料可能已全部覆盖）", attempt)
            return
        try:
            fragment = validate_document(normalize_document({
                "type": "doc", "content": _normalize_model_blocks(nodes),
            }))
            _reject_images(fragment)
            _validate_source_map(fragment, source_map)
        except DocumentValidationError as exc:
            _fail_inputs(db, job, "document_validation_failed", str(exc)[:1000], attempt)
            return

        allowed_runs = {
            source["parse_run_id"] for source in snapshot.get("sources") or []
            if isinstance(source, dict) and isinstance(source.get("parse_run_id"), str)
        }
        source_rows = _resolve_source_rows(db, allowed_runs, source_map)
        if source_rows is None:
            _fail_inputs(db, job, "invalid_sources", "生成内容引用了本次输入之外的原文块", attempt)
            return

        if llm_route:
            notebook = db.get(Notebook, job.notebook_id, populate_existing=True)
            if notebook is not None and notebook.document_revision != snapshot['base_document_revision']:
                job.knowledge_plan_json = None
                job.status = 'pending'
                db.commit()
                return
        try:
            merged = _merge_with_retry(db, job, fragment, source_map, attempt, snapshot, plan)
        except DocumentValidationError as exc:
            db.rollback()
            _fail_inputs(db, job, "invalid_figure", str(exc)[:1000], attempt)
            return
        if merged is None:
            _fail_inputs(
                db, job, "revision_conflict",
                "正文连续并发更新，自动重试次数已用尽；请手动重试生成",
                attempt,
            )
            return
        notebook, next_revision, created = merged
        try:
            source_rows = _resolve_source_rows(db, allowed_runs, source_map)
            if source_rows is None:
                raise DocumentValidationError("生成图片的来源不存在")
            _write_sources(db, notebook, job, source_rows, source_map)
            job.status = "completed"
            job.generator = generator
            job.source_map_json = json.dumps(source_map, ensure_ascii=False)
            job.error_code = job.error_message = None
            job.finished_at = job.updated_at = datetime.now(UTC)
            _complete_inputs(db, job, next_revision)
            if notebook.course_id is not None:
                from app.forest.notebook_relations import enqueue_notebook_relations

                relation_job = enqueue_notebook_relations(db, notebook.course_id, notebook_id=notebook.id,
                    processing_route=snapshot.get('processing_route', 'standard'),
                    provider=snapshot.get('provider', {}))
                job.relation_job_id = relation_job.id if relation_job else None
            db.commit()
        except Exception:
            db.rollback()
            for path in created:
                path.unlink(missing_ok=True)
            raise


def _merge_with_retry(
    db, job: NotebookGenerationJob, fragment: dict[str, Any], source_map: dict[str, list[str]],
    attempt: int, snapshot: dict[str, Any], plan: dict[str, Any],
) -> tuple[Notebook, int, list] | None:
    attempts = 3
    for _ in range(attempts):
        # This write locks the task until body, sources, input statuses and
        # completion commit together. A late cancellation or a second delivery
        # cannot append the same result again.
        if not _guard_processing(db, job.id, attempt):
            db.rollback()
            _checkpoint(db, job, attempt)
            return None
        notebook = db.scalar(select(Notebook).where(
            Notebook.id == job.notebook_id, Notebook.deleted_at.is_(None),
        ).execution_options(populate_existing=True))
        if notebook is None:
            _fail_inputs(db, job, "notebook_unavailable", "笔记已删除或不可用", attempt)
            return None
        current = load_document(notebook.document_json)
        if current.warning:
            _fail_inputs(db, job, "document_validation_failed", current.warning, attempt)
            return None
        content = validate_document(current.content)
        used: set[str] = set()

        def collect(nodes, used=used) -> None:
            for node in nodes or []:
                block_id = (node.get("attrs") or {}).get("blockId")
                if isinstance(block_id, str):
                    used.add(block_id)
                collect(node.get("content"))

        collect(content.get("content"))
        # Move source-map keys with any regenerated block id.
        for node in fragment["content"]:
            attrs = node.get("attrs") or {}
            block_id = attrs.get("blockId")
            if isinstance(block_id, str) and block_id in used:
                new_id = f"ai-{uuid.uuid4().hex[:20]}"
                if block_id in source_map:
                    source_map[new_id] = source_map.pop(block_id)
                attrs["blockId"] = new_id
                node["attrs"] = attrs
                block_id = new_id
            if isinstance(block_id, str):
                used.add(block_id)
        nodes = copy.deepcopy(fragment["content"])
        created = []
        original_keys = set(source_map)
        try:
            append_source_figures(db, notebook.id, snapshot, plan, nodes, source_map, created)
            merged_document = validate_document({
                "type": "doc", "content": [*content["content"], *nodes],
            })
            next_revision, _content = write_document(
                db, notebook, merged_document,
                expected_revision=notebook.document_revision, origin="ai_append",
            )
            db.flush()
            return notebook, next_revision, created
        except DocumentConflict:
            db.rollback()
            for path in created:
                path.unlink(missing_ok=True)
            for key in set(source_map) - original_keys:
                del source_map[key]
            # Reload and retry: append-only merge never overwrites user edits.
            db.expire_all()
            continue
        except Exception:
            db.rollback()
            for path in created:
                path.unlink(missing_ok=True)
            for key in set(source_map) - original_keys:
                del source_map[key]
            raise
    return None


def _reject_images(document: dict[str, Any]) -> None:
    stack = list(document.get("content") or [])
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "image":
            raise DocumentValidationError("AI 生成的补充内容不能新增图片资源")
        stack.extend(node.get("content") or [])


def _normalize_model_blocks(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair model formatting and promote standalone raw LaTeX to math nodes."""
    result = copy.deepcopy(nodes)

    def promote_standalone_latex(node: dict[str, Any]) -> None:
        if node.get("type") != "paragraph":
            return
        children = node.get("content")
        if not isinstance(children, list) or not children or any(
            not isinstance(child, dict) or child.get("type") != "text"
            or child.get("marks") for child in children
        ):
            return
        latex = "".join(child.get("text", "") for child in children).strip()
        if not latex or "\\" not in latex or re.search(r"[，。；：！？]", latex):
            return
        without_text = re.sub(r"\\text\s*\{[^{}]*\}", "", latex)
        if re.search(r"[\u3400-\u9fff]", without_text):
            return
        if not re.fullmatch(r"[-+A-Za-z0-9\s\\{}()[\].,^_=<>|:*\/!]+", without_text):
            return
        if not re.search(
            r"\\(?:cup|cap|setminus|in|notin|subseteq?|supseteq?|mid|frac|sqrt|sum|prod|int|lim|"
            r"cdot|times|leq?|geq?|ne|approx|equiv|to|Rightarrow|Leftrightarrow|mathbb|overline|tag)\b",
            latex,
        ):
            return
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        node.clear()
        node.update({"type": "blockMath", "attrs": {"latex": latex, **(
            {"blockId": attrs["blockId"]} if isinstance(attrs.get("blockId"), str) else {}
        )}})

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        promote_standalone_latex(node)
        kind = node.get("type")
        children = node.get("content")
        if kind == "callout":
            attrs = node.get("attrs")
            if isinstance(attrs, dict) and not attrs.get("title"):
                attrs["title"] = "请核对" if attrs.get("tone") == "warning" else "提示"
        if kind in {"tableHeader", "tableCell", "callout", "example"} and isinstance(children, list):
            inline_types = {"text", "hardBreak", "inlineMath"}
            if children and all(isinstance(child, dict) and child.get("type") in inline_types
                                for child in children):
                node["content"] = [{"type": "paragraph", "content": children}]
        for child in node.get("content") or []:
            visit(child)

    for node in result:
        visit(node)
    return result


def _validate_source_map(document: dict[str, Any], source_map: dict[str, list[str]]) -> None:
    """Validate after normalization, which may assign missing block IDs."""

    ids = [(node.get("attrs") or {}).get("blockId") for node in document["content"]]
    if any(not isinstance(block_id, str) or not block_id for block_id in ids):
        raise DocumentValidationError("生成的正文节点缺少可追溯的块 ID")
    if len(ids) != len(set(ids)):
        raise DocumentValidationError("生成的正文块 ID 重复")
    if set(source_map) != set(ids) or any(
        not isinstance(refs, list) or not refs
        or any(not isinstance(ref, str) or not ref for ref in refs)
        for refs in source_map.values()
    ):
        raise DocumentValidationError("每个生成正文块必须有完整且有效的来源映射")


def _guard_processing(db, job_id: str, attempt: int) -> bool:
    result = db.execute(update(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.status == "processing",
        NotebookGenerationJob.attempt_count == attempt,
    ).values(updated_at=datetime.now(UTC)).execution_options(synchronize_session=False))
    return result.rowcount == 1


def _consumed_parse_runs(db, notebook_id: str) -> list[str]:
    consumed: set[str] = set()
    for raw in db.scalars(select(NotebookGenerationJob.parse_run_ids_json).where(
        NotebookGenerationJob.notebook_id == notebook_id,
        NotebookGenerationJob.status == "completed",
    )):
        try:
            run_ids = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(run_ids, list):
            consumed.update(run_id for run_id in run_ids if isinstance(run_id, str))
    return sorted(consumed)


def _complete_without_append(db, job: NotebookGenerationJob, attempt: int) -> None:
    if not _guard_processing(db, job.id, attempt):
        db.rollback()
        _checkpoint(db, job, attempt)
        return
    notebook = db.get(Notebook, job.notebook_id, populate_existing=True)
    if notebook is None or notebook.deleted_at is not None:
        _fail_inputs(db, job, "notebook_unavailable", "笔记已删除或不可用", attempt)
        return
    job.status = "completed"
    job.source_map_json = "{}"
    job.error_code = job.error_message = None
    job.finished_at = job.updated_at = datetime.now(UTC)
    _complete_inputs(db, job, notebook.document_revision)
    db.commit()


def _checkpoint(db, job: NotebookGenerationJob, attempt: int) -> bool:
    db.refresh(job)
    if job.attempt_count != attempt:
        return False
    if job.status == "cancel_requested":
        cancelled = db.execute(update(NotebookGenerationJob).where(
            NotebookGenerationJob.id == job.id,
            NotebookGenerationJob.status == "cancel_requested",
            NotebookGenerationJob.attempt_count == attempt,
        ).values(status="cancelled", finished_at=datetime.now(UTC), updated_at=datetime.now(UTC))
          .execution_options(synchronize_session=False))
        if cancelled.rowcount:
            cancel_generation_inputs(db, job.id)
        db.commit()
        return False
    return job.status == "processing"


def _resolve_source_rows(
    db, allowed_runs: set[str], source_map: dict[str, list[str]],
) -> dict[tuple[str, str], tuple[DocumentBlock, int]] | None:
    wanted = {block_id for ids in source_map.values() for block_id in ids}
    if not wanted:
        return None
    rows = db.execute(
        select(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(
            DocumentBlock.block_id.in_(wanted),
            DocumentBlock.parse_run_id.in_(list(allowed_runs)),
        )
    ).all()
    resolved = {(row.parse_run_id, row.block_id): (row, page) for row, page in rows}
    if set(wanted) - {block_id for _, block_id in resolved}:
        # Block ids are run-prefixed; a missing id means the snapshot no longer
        # matches the stored evidence.
        return None
    return resolved


def _validate_snapshot_sources(db, notebook_id: str, snapshot: dict[str, Any]) -> None:
    """A queued job can only consume the exact retained, owned source versions."""
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources:
        raise GenerationInputError("生成快照缺少资料", code="snapshot_invalid")
    for source in sources:
        if not isinstance(source, dict):
            raise GenerationInputError("生成快照格式不正确", code="snapshot_invalid")
        run = db.get(DocumentParseRun, source.get("parse_run_id"))
        owner = db.scalar(select(NotebookAsset.id).where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.asset_id == source.get("asset_id"),
            NotebookAsset.is_owner.is_(True), NotebookAsset.detached_at.is_(None),
            NotebookAsset.role == "source_material",
        ))
        if (run is None or run.status != "completed" or run.asset_id != source.get("asset_id")
                or not source.get("ir_fingerprint") or run.fingerprint != source["ir_fingerprint"]
                or owner is None):
            raise GenerationInputError("生成快照的资料归属或解析版本已失效", code="snapshot_invalid")


def _write_sources(
    db, notebook: Notebook, job: NotebookGenerationJob,
    rows: dict[tuple[str, str], tuple[DocumentBlock, int]],
    source_map: dict[str, list[str]],
) -> None:
    fingerprints = {
        (node.get("attrs") or {}).get("blockId"): body_fingerprint(node)
        for node in load_document(notebook.document_json).content.get("content") or []
    }
    existing = {
        (row.block_id, row.document_block_id)
        for row in db.scalars(select(NotebookBlockSource).where(
            NotebookBlockSource.notebook_id == notebook.id,
        )).all()
    }
    for body_block_id, ir_ids in source_map.items():
        for ir_id in ir_ids:
            match = next(
                (value for (run_id, block_id), value in rows.items() if block_id == ir_id), None,
            )
            if match is None:
                continue
            block, page_number = match
            key = (body_block_id, block.id)
            if key in existing:
                continue
            existing.add(key)
            db.add(NotebookBlockSource(
                notebook_id=notebook.id,
                block_id=body_block_id[:64],
                generation_job_id=job.id,
                parse_run_id=block.parse_run_id,
                document_block_id=block.id,
                page_number=page_number,
                confidence=block.confidence,
                body_fingerprint=fingerprints.get(body_block_id),
                status="active",
                created_at=datetime.now(UTC),
            ))
    db.flush()


def _complete_inputs(db, job: NotebookGenerationJob, revision: int) -> None:
    input_ids = _input_asset_ids(job)
    if not input_ids:
        return
    now = datetime.now(UTC)
    db.query(NotebookGenerationInput).filter(
        NotebookGenerationInput.notebook_id == job.notebook_id,
        NotebookGenerationInput.asset_id.in_(input_ids),
        NotebookGenerationInput.status != "completed",
        or_(NotebookGenerationInput.generation_job_id == job.id,
            NotebookGenerationInput.generation_job_id.is_(None)),
    ).update({
        NotebookGenerationInput.status: "completed",
        NotebookGenerationInput.generation_job_id: job.id,
        NotebookGenerationInput.error_code: None,
        NotebookGenerationInput.error_message: None,
        NotebookGenerationInput.updated_at: now,
        NotebookGenerationInput.finished_at: now,
    }, synchronize_session=False)


def _fail_inputs(db, job: NotebookGenerationJob, code: str, message: str, attempt: int) -> None:
    if not _guard_processing(db, job.id, attempt):
        db.rollback()
        _checkpoint(db, job, attempt)
        return
    now = datetime.now(UTC)
    job.status = "failed"
    job.error_code = code[:60]
    job.error_message = message[:2000]
    job.finished_at = job.updated_at = now
    input_ids = _input_asset_ids(job)
    if input_ids:
        db.query(NotebookGenerationInput).filter(
            NotebookGenerationInput.notebook_id == job.notebook_id,
            NotebookGenerationInput.asset_id.in_(input_ids),
            NotebookGenerationInput.status != "completed",
            or_(NotebookGenerationInput.generation_job_id == job.id,
                NotebookGenerationInput.generation_job_id.is_(None)),
        ).update({
            NotebookGenerationInput.status: "generation_failed",
            NotebookGenerationInput.generation_job_id: job.id,
            NotebookGenerationInput.error_code: code[:60],
            NotebookGenerationInput.error_message: message[:2000],
            NotebookGenerationInput.updated_at: now,
        }, synchronize_session=False)
    db.commit()


def _input_asset_ids(job: NotebookGenerationJob) -> list[str]:
    snapshot = _parse_json(job.input_snapshot_json) or {}
    return [
        source["asset_id"] for source in snapshot.get("sources") or []
        if isinstance(source, dict) and isinstance(source.get("asset_id"), str)
    ]


def _parse_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
