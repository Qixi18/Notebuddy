from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.model_utils import new_id
from app.db.models import (
    AssetParseResult,
    Material,
    MaterialPage,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookGenerationCandidate,
    NotebookGenerationJob,
)
from app.notes.assets import AssetUnavailable, assert_notebook_asset
from app.notes.document import (
    DocumentValidationError,
    dump_document,
    load_document,
    normalize_document,
    validate_document,
)
from app.notes.history import record_snapshot
from app.schemas.generation import (
    NotebookGenerationApply,
    NotebookGenerationCreate,
    NotebookGenerationJobRead,
)
from app.workers.notebook_generation_worker import PROMPT_VERSION

router = APIRouter()


def _job_read(db: Session, job: NotebookGenerationJob) -> dict:
    candidate = db.scalar(select(NotebookGenerationCandidate).where(
        NotebookGenerationCandidate.job_id == job.id,
    ))
    candidate_document = load_document(candidate.document_json) if candidate else None
    return {
        "id": job.id, "notebook_id": job.notebook_id, "status": job.status,
        "base_document_revision": job.base_document_revision, "model": job.model,
        "prompt_version": job.prompt_version, "attempt_count": job.attempt_count,
        "error_code": job.error_code, "error_message": job.error_message,
        "created_at": job.created_at, "updated_at": job.updated_at,
        "finished_at": job.finished_at,
        "candidate": ({
            "id": candidate.id, "job_id": candidate.job_id,
            "notebook_id": candidate.notebook_id,
            "document": candidate_document.content,
            "status": candidate.status, "created_at": candidate.created_at,
            "expires_at": candidate.expires_at,
        } if candidate else None),
    }


def _same_generation_request(
    job: NotebookGenerationJob,
    *,
    notebook_id: str,
    asset_ids: list[str],
    base_revision: int,
) -> bool:
    if job.notebook_id != notebook_id or job.base_document_revision != base_revision:
        return False
    try:
        snapshot = json.loads(job.input_snapshot_json)
        stored_ids = [source["asset_id"] for source in snapshot["sources"]]
    except (KeyError, TypeError, ValueError):
        return False
    return stored_ids == asset_ids


@router.post("/notebooks/{notebook_id}/generation-jobs", response_model=NotebookGenerationJobRead,
             status_code=202)
def create_generation_job(
    notebook_id: str,
    payload: NotebookGenerationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
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

    existing = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == notebook_id,
        NotebookGenerationJob.idempotency_key == key,
    ))
    if existing is not None:
        if not _same_generation_request(
            existing, notebook_id=notebook_id, asset_ids=asset_ids,
            base_revision=notebook.document_revision,
        ):
            raise HTTPException(409, "幂等键已用于不同的资料或正文版本")
        return _job_read(db, existing)

    sources: list[dict] = []
    for asset_id in asset_ids:
        try:
            asset = assert_notebook_asset(db, asset_id, notebook_id)
        except AssetUnavailable as exc:
            raise HTTPException(422, f"输入资源不可用：{asset_id}") from exc
        text = ""
        extraction: dict = {}
        evidence: list[dict] = []
        if asset.media_type == "image":
            parsed = db.scalar(select(AssetParseResult).where(
                AssetParseResult.asset_id == asset.id,
                AssetParseResult.status.in_(("completed", "completed_with_warnings")),
            ).order_by(AssetParseResult.created_at.desc()).limit(1))
            if parsed and parsed.result_json:
                try:
                    text = str((json.loads(parsed.result_json) or {}).get("text") or "")
                except (TypeError, ValueError):
                    text = ""
            if not text.strip():
                raise HTTPException(409, f"图片尚无可用 OCR 结果：{asset.original_name}")
            extraction = {
                "kind": "image_ocr", "result_id": parsed.id,
                "provider": parsed.provider, "parser_version": parsed.parser_version,
                "status": parsed.status,
            }
            evidence.append({"type": "image_parse_result", "id": parsed.id})
        else:
            material = db.scalar(select(Material).where(Material.asset_id == asset.id))
            if material is not None:
                pages = db.scalars(select(MaterialPage).where(
                    MaterialPage.material_id == material.id,
                    MaterialPage.is_active.is_(True),
                ).order_by(MaterialPage.page_number)).all()
                text = "\n".join(
                    f"[{page.location_label or page.page_number}] {page.title or ''}\n{page.raw_text}"
                    for page in pages
                )
                extraction = {
                    "kind": "material_pages", "material_id": material.id,
                    "parser_version": material.parser_version,
                }
                evidence = [{
                    "type": "material_page", "id": page.id,
                    "page_number": page.page_number,
                    "location_label": page.location_label,
                    "stable_location_key": page.stable_location_key,
                    "extraction_method": page.extraction_method,
                    "confidence": page.confidence,
                    "text_sha256": hashlib.sha256(page.raw_text.encode("utf-8")).hexdigest(),
                } for page in pages]
            if not text.strip():
                raise HTTPException(409, f"文档尚无可用解析结果：{asset.original_name}")
        included_text = text[:150_000]
        sources.append({
            "asset_id": asset.id, "name": asset.original_name,
            "mime_type": asset.mime_type,
            "asset_sha256": asset.sha256,
            "extraction": extraction,
            "evidence": evidence,
            "text_sha256": hashlib.sha256(included_text.encode("utf-8")).hexdigest(),
            "text": included_text,
        })

    current = load_document(notebook.document_json)
    request_fingerprint = hashlib.sha256(json.dumps({
        "notebook_id": notebook_id,
        "base_document_revision": notebook.document_revision,
        "current_document_sha256": hashlib.sha256(
            json.dumps(current.content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "sources": [{
            "asset_id": source["asset_id"],
            "asset_sha256": source["asset_sha256"],
            "extraction": source["extraction"],
            "evidence": source["evidence"],
            "text_sha256": source["text_sha256"],
        } for source in sources],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    snapshot = {
        "notebook_title": notebook.title,
        "base_document_revision": notebook.document_revision,
        "current_document": current.content,
        "sources": sources,
    }
    now = datetime.now(UTC)
    job = NotebookGenerationJob(
        id=new_id(), notebook_id=notebook_id, idempotency_key=key,
        request_fingerprint=request_fingerprint,
        status="pending", base_document_revision=notebook.document_revision,
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        model=settings.deepseek_model, prompt_version=PROMPT_VERSION,
        schema_version=2, attempt_count=0, created_at=now, updated_at=now,
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
        if duplicate is not None:
            if _same_generation_request(
                duplicate, notebook_id=notebook_id, asset_ids=asset_ids,
                base_revision=notebook.document_revision,
            ):
                return _job_read(db, duplicate)
            raise HTTPException(409, "幂等键已用于不同的资料或正文版本") from exc
        raise HTTPException(409, "生成任务创建冲突") from exc
    db.refresh(job)
    return _job_read(db, job)


@router.get("/notebooks/{notebook_id}/generation-jobs", response_model=list[NotebookGenerationJobRead])
def list_generation_jobs(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    jobs = db.scalars(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == notebook_id,
    ).order_by(NotebookGenerationJob.created_at.desc()).limit(100)).all()
    return [_job_read(db, job) for job in jobs]


@router.get("/notebooks/{notebook_id}/generation-jobs/{job_id}", response_model=NotebookGenerationJobRead)
def get_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/apply",
             response_model=NotebookGenerationJobRead)
def apply_generation_candidate(
    notebook_id: str, job_id: str, payload: NotebookGenerationApply,
    db: Session = Depends(get_db),
):
    notebook = db.get(Notebook, notebook_id)
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    candidate = db.scalar(select(NotebookGenerationCandidate).where(
        NotebookGenerationCandidate.job_id == job_id,
        NotebookGenerationCandidate.notebook_id == notebook_id,
    ))
    if notebook is None or notebook.deleted_at is not None or job is None or candidate is None:
        raise HTTPException(404, "可应用的生成候选不存在")
    if candidate.status != "pending_review" or job.status != "candidate_ready":
        raise HTTPException(409, "该候选已处理或不可应用")
    if (payload.expected_revision != job.base_document_revision
            or notebook.document_revision != job.base_document_revision):
        candidate.status = "stale"
        job.status = "conflict"
        job.error_code = "revision_conflict"
        job.error_message = "笔记正文已变化；请基于最新正文重新生成或手动合并候选"
        db.commit()
        raise HTTPException(409, job.error_message)
    try:
        stored_candidate = load_document(candidate.document_json)
        if stored_candidate.warning:
            raise DocumentValidationError(stored_candidate.warning)
        content = normalize_document(stored_candidate.content)
        validate_document(content)
    except (ValueError, DocumentValidationError) as exc:
        raise HTTPException(422, f"候选文档未通过校验：{exc}") from exc
    image_nodes: list[dict] = []

    def collect_images(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "image" and isinstance(node.get("attrs"), dict):
            image_nodes.append(node["attrs"])
        for child in node.get("content") or []:
            collect_images(child)

    collect_images(content)
    legacy_attachment_ids = {
        attrs["attachmentId"] for attrs in image_nodes if isinstance(attrs.get("attachmentId"), str)
    }
    stable_asset_ids = {
        attrs["assetId"] for attrs in image_nodes if isinstance(attrs.get("assetId"), str)
    }
    if legacy_attachment_ids:
        owned = set(db.scalars(select(NotebookAttachment.id).where(
            NotebookAttachment.notebook_id == notebook_id,
            NotebookAttachment.id.in_(legacy_attachment_ids),
        )).all())
        if owned != legacy_attachment_ids:
            raise HTTPException(422, "候选包含不属于当前笔记的图片资源")
    try:
        for asset_id in stable_asset_ids:
            assert_notebook_asset(db, asset_id, notebook_id)
    except AssetUnavailable as exc:
        raise HTTPException(422, "候选包含不可用或不属于当前笔记的图片资源") from exc
    next_revision = notebook.document_revision + 1
    result = db.execute(update(Notebook).where(
        Notebook.id == notebook_id,
        Notebook.document_revision == payload.expected_revision,
        Notebook.deleted_at.is_(None),
    ).values(
        document_json=dump_document(content), document_revision=next_revision,
        updated_at=datetime.now(UTC),
    ))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记正文已被其他编辑更新，请刷新后再应用")
    record_snapshot(db, notebook_id, next_revision, content, origin="ai_candidate")
    candidate.status = "applied"
    job.status = "applied"
    job.finished_at = datetime.now(UTC)
    job.updated_at = job.finished_at
    db.commit()
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/reject",
             response_model=NotebookGenerationJobRead)
def reject_generation_candidate(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    candidate = db.scalar(select(NotebookGenerationCandidate).where(
        NotebookGenerationCandidate.job_id == job_id,
        NotebookGenerationCandidate.notebook_id == notebook_id,
    ))
    if job is None or candidate is None or candidate.status != "pending_review":
        raise HTTPException(404, "待审核候选不存在")
    candidate.status = "rejected"
    job.status = "rejected"
    job.finished_at = datetime.now(UTC)
    job.updated_at = job.finished_at
    db.commit()
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/retry",
             response_model=NotebookGenerationJobRead, status_code=202)
def retry_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    if job.status not in {"failed", "conflict"} or job.attempt_count >= 3:
        raise HTTPException(409, "任务当前不可重试或已达到 3 次执行上限")
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    job.status = "pending"
    job.base_document_revision = notebook.document_revision
    snapshot = json.loads(job.input_snapshot_json)
    current = load_document(notebook.document_json)
    snapshot["base_document_revision"] = notebook.document_revision
    snapshot["current_document"] = current.content
    job.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    job.updated_at = datetime.now(UTC)
    db.commit()
    return _job_read(db, job)


@router.post("/notebooks/{notebook_id}/generation-jobs/{job_id}/cancel",
             response_model=NotebookGenerationJobRead)
def cancel_generation_job(notebook_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(NotebookGenerationJob).where(
        NotebookGenerationJob.id == job_id,
        NotebookGenerationJob.notebook_id == notebook_id,
    ))
    if job is None:
        raise HTTPException(404, "生成任务不存在")
    if job.status == "pending":
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        job.updated_at = job.finished_at
    elif job.status == "processing":
        job.status = "cancel_requested"
        job.updated_at = datetime.now(UTC)
    else:
        raise HTTPException(409, "任务已进入不可取消状态")
    db.commit()
    return _job_read(db, job)
