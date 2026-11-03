"""Application use cases for source Material parse lifecycle."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Asset,
    AssetProcessingJob,
    DocumentPage,
    DocumentParseRun,
    Material,
    MaterialPage,
    NotebookAsset,
    NotebookGenerationInput,
    ProcessingJob,
)
from app.document_processing.adapters import mineru as mineru_adapter
from app.document_processing.config import provider_snapshot, resolve_route
from app.parsers.ocr import status as ocr_status
from app.services.errors import ApplicationError


def _material(db: Session, material_id: str) -> Material:
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is not None:
        raise ApplicationError(404, "资料不存在")
    return material


def _source_exists(material: Material) -> None:
    if not (settings.originals_dir / material.stored_filename).is_file():
        raise ApplicationError(410, "原始课件文件不存在，请重新上传")


def _queue_parse(db: Session, material: Material, kind: str) -> ProcessingJob:
    material.status = "pending"
    job = ProcessingJob(material_id=material.id, kind=kind)
    db.add(job)
    db.flush()
    if material.asset_id:
        row = db.scalar(select(NotebookGenerationInput).where(
            NotebookGenerationInput.asset_id == material.asset_id,
        ))
        if row is not None and row.status not in {"completed", "generating"}:
            row.parse_job_id = job.id
            row.status = "waiting_parse"
            row.retry_count += 1
            row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


def retry_material_parse(db: Session, material_id: str) -> ProcessingJob:
    material = _material(db, material_id)
    if material.status != "failed":
        raise ApplicationError(409, "只有解析失败的资料可以重试")
    _source_exists(material)
    return _queue_parse(db, material, "parse_material")


def reparse_material(db: Session, material_id: str) -> ProcessingJob:
    material = _material(db, material_id)
    active = db.scalar(select(ProcessingJob).where(
        ProcessingJob.material_id == material_id,
        ProcessingJob.status.in_(("pending", "processing")),
    ).limit(1))
    if active is not None:
        raise ApplicationError(409, "资料已有正在处理的任务")
    _source_exists(material)
    return _queue_parse(db, material, "reparse_material")


def request_material_ocr(db: Session, material_id: str) -> ProcessingJob:
    material = _material(db, material_id)
    if mineru_adapter.configured():
        if not mineru_adapter.availability()["available"]:
            raise ApplicationError(501, "已选择 MinerU，但当前后端环境没有安装 MinerU")
        return reparse_material(db, material_id)
    capability = ocr_status()
    if capability["status"] != "ready":
        raise ApplicationError(
            501,
            "OCR 当前不可用：请启用 NOTEBOOK_OCR_ENABLED，并安装 PaddleOCR、RapidOCR "
            "或 Tesseract；原生 PDF 渲染需要 PyMuPDF 或 pypdfium2。",
        )
    active = db.scalar(select(ProcessingJob).where(
        ProcessingJob.material_id == material_id,
        ProcessingJob.status.in_(("pending", "processing")),
    ).limit(1))
    if active is not None:
        raise ApplicationError(409, "资料已有正在处理的任务")
    asset_id = material.asset_id or material.id
    candidate = db.scalar(select(DocumentPage.id).join(
        DocumentParseRun, DocumentParseRun.id == DocumentPage.parse_run_id,
    ).where(
        DocumentParseRun.asset_id == asset_id,
        DocumentParseRun.is_current.is_(True),
        DocumentPage.status == "needs_ocr",
    ).limit(1))
    if candidate is None:
        candidate = db.scalar(select(MaterialPage.id).where(
            MaterialPage.material_id == material_id,
            MaterialPage.is_active.is_(True),
            MaterialPage.parse_status == "ocr_candidate",
        ).limit(1))
    if candidate is None:
        raise ApplicationError(409, "当前资料没有待 OCR 的位置")
    material.status = "pending"
    job = ProcessingJob(material_id=material.id, kind="ocr_material")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def switch_asset_processing_route(
    db: Session, asset_id: str, requested_route: str,
) -> dict[str, str]:
    """Change the parser route and enqueue the matching source parse atomically."""
    from app.document_processing.config import ensure_vision_preflight

    try:
        route = resolve_route(requested_route)
        if route == "llm":
            ensure_vision_preflight()
    except ValueError as exc:
        status = 409 if "预检" in str(exc) or "视觉模型" in str(exc) else 422
        raise ApplicationError(status, str(exc)) from exc

    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ApplicationError(404, "资源不存在")
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if owner is None or asset.state != "ready":
        raise ApplicationError(404, "原始资料当前不可用")

    material = db.scalar(select(Material).where(Material.asset_id == asset_id))
    active = (
        db.scalar(select(ProcessingJob.id).where(
            ProcessingJob.material_id == material.id,
            ProcessingJob.status.in_(("pending", "processing")),
        ))
        if material else db.scalar(select(AssetProcessingJob.id).where(
            AssetProcessingJob.asset_id == asset_id,
            AssetProcessingJob.status.in_(("pending", "processing")),
        ))
    )
    if active:
        raise ApplicationError(409, "资料仍在处理中，请取消或等待后再切换路线")

    asset.processing_route = route
    asset.processing_config_json = json.dumps(provider_snapshot())
    if material:
        material.processing_route = route
        material.status = "pending"
        job = ProcessingJob(material_id=material.id, kind="reparse_material")
    else:
        job = AssetProcessingJob(
            asset_id=asset.id, notebook_id=owner.notebook_id,
            owner_link_id=owner.id, kind="image_reparse", status="pending",
        )
    db.add(job)
    db.flush()
    input_row = db.scalar(select(NotebookGenerationInput).where(
        NotebookGenerationInput.asset_id == asset_id,
    ))
    if input_row is not None and input_row.status not in {"completed", "generating"}:
        input_row.parse_job_id = job.id
        input_row.status = "waiting_parse"
        input_row.error_code = input_row.error_message = None
        input_row.updated_at = datetime.now(UTC)
    db.commit()
    return {"asset_id": asset_id, "processing_route": route, "job_id": job.id}


def cancel_asset_processing(db: Session, asset_id: str) -> dict[str, bool]:
    if db.get(Asset, asset_id) is None:
        raise ApplicationError(404, "资源不存在")
    material = db.scalar(select(Material).where(Material.asset_id == asset_id))
    model = ProcessingJob if material else AssetProcessingJob
    condition = model.material_id == material.id if material else model.asset_id == asset_id
    active = db.scalars(select(model).where(
        condition, model.status.in_(("pending", "processing")),
    )).all()
    if not active:
        raise ApplicationError(409, "没有可取消的读取任务")
    now = datetime.now(UTC)
    for job in active:
        job.status = "failed"
        job.error_code = "cancelled"
        job.error_message = "读取已取消，已完成页面保留，可重试继续"
        job.attempt_count += 1
        job.finished_at = now
    if material:
        material.status = "failed"
    input_row = db.scalar(select(NotebookGenerationInput).where(
        NotebookGenerationInput.asset_id == asset_id,
    ))
    if input_row is not None and input_row.status not in {"completed", "generating"}:
        input_row.status = "parse_failed"
        input_row.error_code = "cancelled"
        input_row.error_message = "读取已取消，已完成页面保留，可重试继续"
        input_row.finished_at = now
        input_row.updated_at = now
    db.commit()
    return {"cancelled": True}


def retry_asset_parse(db: Session, asset_id: str) -> AssetProcessingJob:
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    asset = db.get(Asset, asset_id)
    if owner is None or asset is None or asset.state != "ready" or asset.media_type != "image":
        raise ApplicationError(404, "可重试的原始图片不存在")
    attempts = db.scalar(select(func.count(AssetProcessingJob.id)).where(
        AssetProcessingJob.asset_id == asset_id,
    )) or 0
    if attempts >= 5:
        raise ApplicationError(409, "图片解析最多尝试 5 次；请先检查 OCR 配置或更换图片")
    active = db.scalar(select(AssetProcessingJob.id).where(
        AssetProcessingJob.asset_id == asset_id,
        AssetProcessingJob.status.in_(("pending", "processing")),
    ))
    if active:
        raise ApplicationError(409, "图片解析任务已在队列中")
    job = AssetProcessingJob(
        asset_id=asset_id, notebook_id=owner.notebook_id, owner_link_id=owner.id,
        kind="image_reparse", status="pending", attempt_count=0,
    )
    db.add(job)
    db.flush()
    input_row = db.scalar(select(NotebookGenerationInput).where(
        NotebookGenerationInput.asset_id == asset_id,
    ))
    if input_row is not None and input_row.status != "completed":
        input_row.parse_job_id = job.id
        input_row.status = "waiting_parse"
        input_row.retry_count += 1
        input_row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job
