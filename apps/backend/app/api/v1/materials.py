from __future__ import annotations

import shutil
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course, ensure_material
from app.core.config import settings
from app.db.database import get_db
from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    AssetParseResult,
    AssetProcessingJob,
    DocumentBlock,
    DocumentPage,
    DocumentParseRun,
    Material,
    MaterialPage,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookBlockSource,
    NotebookGenerationInput,
    NotebookSection,
    NotebookUploadBatch,
    ProcessingJob,
    WebSource,
    utc_now,
)
from app.document_processing.adapters import mineru as mineru_adapter
from app.document_processing.ir import QualityReport
from app.document_processing.service import (
    current_run as current_parse_run,
)
from app.document_processing.service import (
    latest_run as latest_parse_run,
)
from app.document_processing.service import (
    load_ir,
    page_render,
)
from app.notes.assets import (
    AssetUnavailable,
    assert_notebook_asset,
    remove_notebook_asset,
    storage_path,
)
from app.notes.notebook import bump_order_revision
from app.parsers.ocr import status as ocr_status
from app.schemas.api import (
    CoverageRead,
    DeletionPreview,
    JobRead,
    MaterialRead,
    PageEvidenceRead,
    PageRead,
    UploadMaterialResponse,
    WebSourceRead,
)
from app.schemas.assets import AssetProcessingJobRead, AssetRead, AssetUploadRead
from app.schemas.document import (
    DocumentBlockRead,
    DocumentIRRead,
    DocumentRunRead,
)
from app.services.course_scope import material_course_id, materials_for_course
from app.services.coverage import material_coverage
from app.services.deletion import (
    DeletionConflict,
    impact_preview,
    soft_delete_material,
)
from app.services.image_assets import ImageUploadRejected, ingest_source_image
from app.services.notebook_generation_inputs import (
    batch_status as notebook_upload_batch_status,
)
from app.services.notebook_generation_inputs import (
    close_upload_batch,
    ensure_upload_batch,
    register_generation_input,
)
from app.services.uploads import UploadRejected, ingest_document

router = APIRouter()


def _asset_read(asset: Asset, role: str, notebook_id: str) -> dict:
    return {
        "id": asset.id, "source_type": asset.source_type,
        "media_type": asset.media_type, "mime_type": asset.mime_type,
        "original_name": asset.original_name, "byte_size": asset.byte_size,
        "sha256": asset.sha256, "state": asset.state, "role": role,
        "content_url": f"/api/v1/notebooks/{notebook_id}/assets/{asset.id}/content",
        "created_at": asset.created_at,
    }


@router.get("/notebooks/{notebook_id}/assets", response_model=list[AssetRead])
def list_notebook_assets(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    rows = db.execute(select(Asset, NotebookAsset.role, NotebookAsset.notebook_id).join(
        NotebookAsset, NotebookAsset.asset_id == Asset.id,
    ).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ).order_by(NotebookAsset.created_at.desc())).all()
    return [_asset_read(asset, role, owner_notebook_id) for asset, role, owner_notebook_id in rows]


@router.get("/notebooks/{notebook_id}/detached-assets", response_model=list[AssetRead])
def list_detached_notebook_assets(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    rows = db.execute(select(Asset, NotebookAsset.role, NotebookAsset.notebook_id).join(
        NotebookAsset, NotebookAsset.asset_id == Asset.id,
    ).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_not(None),
        Asset.state == "ready",
    ).order_by(NotebookAsset.detached_at.desc())).all()
    return [_asset_read(asset, role, owner_notebook_id) for asset, role, owner_notebook_id in rows]


@router.post("/notebooks/{notebook_id}/assets/{asset_id}/restore", response_model=AssetRead)
def restore_notebook_asset(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
    ))
    asset = db.get(Asset, asset_id)
    if owner is None or asset is None:
        raise HTTPException(404, "这份资源不属于当前 Notebook")
    if owner.detached_at is None:
        return _asset_read(asset, owner.role, notebook_id)
    if asset.state != "ready":
        raise HTTPException(409, "资源文件已不可恢复，请重新上传原文件")
    active_owner = db.scalar(select(NotebookAsset.id).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if active_owner is not None:
        raise HTTPException(409, "资源已归属其他位置，无法恢复到当前 Notebook")
    try:
        storage_path(asset)
    except AssetUnavailable as exc:
        raise HTTPException(409, "资源文件缺失，无法恢复") from exc
    owner.detached_at = None
    db.commit()
    return _asset_read(asset, owner.role, notebook_id)


@router.post("/notebooks/{notebook_id}/assets/{asset_id}/inline", response_model=AssetRead)
def mark_asset_inline(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    try:
        asset = assert_notebook_asset(db, asset_id, notebook_id)
    except AssetUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    if asset.media_type != "image":
        raise HTTPException(422, "只有图片资源可以插入正文")
    link = db.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.role == "inline_image",
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
        NotebookAsset.asset_id == asset_id,
    ))
    if link is not None:
        return _asset_read(asset, "inline_image", notebook_id)

    # Inline note images live beside the Notebook's other image files. Keep
    # source-material assets intact and make a separately owned inline copy.
    inline_id = new_id()
    extension = asset.extension.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        extension = ".png"
    storage_key = f"notebooks/{notebook_id}/images/{inline_id}{extension}"
    target = (settings.data_dir / storage_key).resolve()
    base = (settings.data_dir / "notebooks" / notebook_id / "images").resolve()
    if not target.is_relative_to(base):
        raise HTTPException(400, "图片存储路径不合法")
    try:
        source = storage_path(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except (AssetUnavailable, OSError) as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(409, "无法复制图片到笔记目录") from exc
    now = utc_now()
    inline_asset = Asset(
        id=inline_id, source_type="user_upload", media_type="image",
        mime_type=asset.mime_type, extension=extension,
        original_name=asset.original_name, storage_key=storage_key,
        byte_size=asset.byte_size, sha256=asset.sha256, state="ready",
        created_at=now, verified_at=now,
    )
    db.add_all([inline_asset, NotebookAsset(
        notebook_id=notebook_id, asset_id=inline_id, role="inline_image",
        is_owner=True, created_at=now,
    )])
    try:
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return _asset_read(inline_asset, "inline_image", notebook_id)


@router.delete("/notebooks/{notebook_id}/assets/{asset_id}")
def delete_notebook_asset(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(404, "笔记不存在")
    try:
        state = remove_notebook_asset(db, notebook_id, asset_id)
    except AssetUnavailable as exc:
        message = str(exc)
        raise HTTPException(404 if "不存在" in message else 409, message) from exc
    return {"asset_id": asset_id, "state": state}


@router.post("/notebooks/{notebook_id}/assets", response_model=AssetUploadRead,
             status_code=201)
async def upload_notebook_asset(
    notebook_id: str,
    file: UploadFile = File(...),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
):
    filename = file.filename or "upload"
    extension = Path(filename).suffix.lower()
    if extension in settings.allowed_extensions:
        data = await file.read(settings.max_upload_bytes + 1)
        notebook = db.get(Notebook, notebook_id)
        if notebook is None or notebook.deleted_at is not None:
            raise HTTPException(404, "笔记不存在")
        batch = ensure_upload_batch(
            db, notebook_id, upload_batch_id, close_if_new=upload_batch_id is None,
        )
        try:
            material, document_job = ingest_document(
                db, course_id=notebook.course_id, notebook_id=notebook_id,
                source=BytesIO(data), filename=filename,
                lecture_title=filename, topic_title="",
                media_type=file.content_type, upload_batch_id=batch.id,
            )
        except UploadRejected as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        asset = db.get(Asset, material.asset_id)
        if asset is None:
            raise HTTPException(500, "资源元数据未创建")
        register_generation_input(
            db, notebook_id=notebook_id, asset_id=asset.id, batch_id=batch.id,
            parse_kind="material", parse_job_id=document_job.id,
        )
        db.commit()
        return {"asset": _asset_read(asset, "source_material", notebook_id),
                "processing_job": None, "upload_batch_id": batch.id}
    data = await file.read(20 * 1024 * 1024 + 1)
    try:
        notebook = db.get(Notebook, notebook_id)
        if notebook is None or notebook.deleted_at is not None:
            raise HTTPException(404, "笔记不存在")
        batch = ensure_upload_batch(
            db, notebook_id, upload_batch_id, close_if_new=upload_batch_id is None,
        )
        asset, job = ingest_source_image(
            db, notebook_id=notebook_id, filename=filename, data=data,
            upload_batch_id=batch.id,
        )
    except ImageUploadRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    register_generation_input(
        db, notebook_id=notebook_id, asset_id=asset.id, batch_id=batch.id,
        parse_kind="image", parse_job_id=job.id if job else None,
    )
    db.commit()
    return {
        "asset": _asset_read(asset, "source_material", notebook_id),
        "upload_batch_id": batch.id,
        "processing_job": ({
            "id": job.id, "asset_id": job.asset_id, "status": job.status,
            "attempt_count": job.attempt_count, "error_code": job.error_code,
            "error_message": job.error_message, "created_at": job.created_at,
            "finished_at": job.finished_at,
        } if job else None),
    }


@router.post("/notebooks/{notebook_id}/upload-batches/{batch_id}/complete")
def complete_notebook_upload_batch(notebook_id: str, batch_id: str,
                                   db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batch = close_upload_batch(db, notebook_id, batch_id)
    return notebook_upload_batch_status(db, batch)


@router.get("/notebooks/{notebook_id}/upload-batches/{batch_id}")
def get_notebook_upload_batch(notebook_id: str, batch_id: str,
                              db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batch = db.get(NotebookUploadBatch, batch_id)
    if batch is None or batch.notebook_id != notebook_id:
        raise HTTPException(404, "上传批次不存在")
    return notebook_upload_batch_status(db, batch)


@router.get("/notebooks/{notebook_id}/upload-batches")
def list_notebook_upload_batches(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batches = db.scalars(select(NotebookUploadBatch).where(
        NotebookUploadBatch.notebook_id == notebook_id,
    ).order_by(NotebookUploadBatch.created_at.desc()).limit(30)).all()
    return [notebook_upload_batch_status(db, batch) for batch in batches]


@router.get("/assets/{asset_id}/parse-results")
def list_asset_parse_results(asset_id: str, db: Session = Depends(get_db)):
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id, NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if owner is None:
        raise HTTPException(404, "资源不存在")
    return list(db.scalars(select(AssetParseResult).where(
        AssetParseResult.asset_id == asset_id,
    ).order_by(AssetParseResult.created_at.desc())).all())


@router.get("/assets/{asset_id}/parse-runs", response_model=list[DocumentRunRead])
def list_asset_parse_runs(asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db)):
    _ensure_asset(db, asset_id, notebook_id)
    runs = db.scalars(select(DocumentParseRun).where(
        DocumentParseRun.asset_id == asset_id,
    ).order_by(DocumentParseRun.created_at.desc())).all()
    return [_run_payload(run) for run in runs]


@router.get("/assets/{asset_id}/document", response_model=DocumentIRRead)
def get_asset_document(asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db)):
    _ensure_asset(db, asset_id, notebook_id)
    run = current_parse_run(db, asset_id)
    if run is None:
        latest = latest_parse_run(db, asset_id)
        if latest is not None and latest.status == "failed":
            raise HTTPException(409, {
                "code": latest.error_code or "parse_failed",
                "message": latest.error_message or "解析失败",
                "run_id": latest.id,
            })
        raise HTTPException(404, "该资料还没有完成的解析版本")
    return _document_payload(db, run)


@router.get("/assets/{asset_id}/document/runs/{run_id}", response_model=DocumentIRRead)
def get_asset_document_run(asset_id: str, run_id: str, notebook_id: str | None = None, db: Session = Depends(get_db)):
    _ensure_asset(db, asset_id, notebook_id)
    run = db.get(DocumentParseRun, run_id)
    if run is None or run.asset_id != asset_id:
        raise HTTPException(404, "解析版本不存在")
    if run.status != "completed":
        raise HTTPException(409, {
            "code": run.error_code or "parse_incomplete",
            "message": run.error_message or "解析尚未完成",
            "run_id": run.id,
        })
    return _document_payload(db, run)


@router.get("/assets/{asset_id}/document/pages/{page_number}/evidence",
            response_model=list[DocumentBlockRead])
def get_document_page_evidence(asset_id: str, page_number: int, notebook_id: str | None = None,
                               run_id: str | None = None, db: Session = Depends(get_db)):
    _ensure_asset(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise HTTPException(404, "该资料还没有完成的解析版本")
    document = load_ir(db, run)
    page = next((item for item in document.pages if item.page_number == page_number), None)
    if page is None:
        raise HTTPException(404, "页面不存在")
    payloads = []
    for block in page.blocks:
        payload = _block_payload(block)
        if block.figure and block.figure.image_key:
            payload["figure"]["image_key"] = _figure_image_url(
                run.asset_id, run.id, block.figure.image_key,
            )
        payloads.append(payload)
    return payloads


@router.get("/assets/{asset_id}/document/pages/{page_number}/render")
def get_document_page_render(asset_id: str, page_number: int, notebook_id: str | None = None,
                             run_id: str | None = None, db: Session = Depends(get_db)):
    asset = _ensure_asset(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise HTTPException(404, "该资料还没有完成的解析版本")
    if (asset.extension or "").lower() != ".pdf":
        try:
            path = storage_path(asset)
        except AssetUnavailable as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(path, media_type=asset.mime_type,
                            headers={"Cache-Control": "private, max-age=86400",
                                     "Content-Disposition": "inline"})
    path = page_render(db, run, page_number)
    if path is None or not path.is_file():
        raise HTTPException(404, "该页无法渲染")
    db.commit()
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/assets/{asset_id}/document/figures/{image_token}")
def get_document_figure_image(
    asset_id: str, image_token: str, notebook_id: str | None = None,
    run_id: str | None = None, db: Session = Depends(get_db),
):
    _ensure_asset(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise HTTPException(404, "解析版本不存在")
    document = load_ir(db, run)
    figure_key = next((
        block.figure.image_key
        for page in document.pages for block in page.blocks
        if block.figure and block.figure.image_key
        and Path(block.figure.image_key).name.rsplit(".", 1)[0] == image_token
    ), None)
    if not figure_key:
        raise HTTPException(404, "图片证据不存在")
    root = settings.data_dir.resolve()
    path = (root / figure_key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise HTTPException(404, "图片证据不可用")
    if path is None or not path.is_file():
        raise HTTPException(404, "图片证据不可用")
    media_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/assets/{asset_id}/document/coverage")
def get_document_coverage(asset_id: str, notebook_id: str | None = None,
                          run_id: str | None = None, db: Session = Depends(get_db)):
    asset = _ensure_asset(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise HTTPException(404, "该资料还没有完成的解析版本")
    rows = db.execute(
        select(DocumentBlock.block_id, DocumentPage.page_number, DocumentBlock.text)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(DocumentBlock.parse_run_id == run.id, DocumentBlock.text != "")
    ).all()
    links = db.execute(
        select(NotebookBlockSource, Notebook)
        .join(Notebook, Notebook.id == NotebookBlockSource.notebook_id)
        .where(NotebookBlockSource.parse_run_id == run.id)
    ).all()
    cited: dict[str, list[dict]] = {}
    for link, notebook in links:
        cited.setdefault(link.block_id, []).append({
            "notebook_id": notebook.id, "notebook_title": notebook.title,
            "block_id": link.block_id, "page_number": link.page_number,
        })
    blocks = []
    for block_id, page_number, text in rows:
        blocks.append({
            "block_id": block_id, "page_number": page_number, "quote": text[:300],
            "citations": cited.get(block_id, []),
        })
    total = len(blocks)
    cited_total = sum(1 for block in blocks if block["citations"])
    pages: dict[int, dict[str, int]] = {}
    for block in blocks:
        bucket = pages.setdefault(block["page_number"], {"total": 0, "cited": 0})
        bucket["total"] += 1
        if block["citations"]:
            bucket["cited"] += 1
    return {
        "asset_id": asset.id, "asset_name": asset.original_name,
        "parse_run_id": run.id, "total_blocks": total, "cited_blocks": cited_total,
        "pages": [{"page_number": number, **counts} for number, counts in sorted(pages.items())],
        "blocks": blocks,
    }


def _ensure_asset(db: Session, asset_id: str, notebook_id: str | None = None) -> Asset:
    if notebook_id:
        try:
            return assert_notebook_asset(db, asset_id, notebook_id)
        except AssetUnavailable as exc:
            raise HTTPException(404, str(exc)) from exc
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "资源不存在")
    return asset


def _selected_completed_run(db: Session, asset_id: str, run_id: str | None) -> DocumentParseRun | None:
    run = current_parse_run(db, asset_id) if run_id is None else db.get(DocumentParseRun, run_id)
    if run is not None and (run.asset_id != asset_id or run.status != "completed"):
        raise HTTPException(404, "解析版本不存在或尚未完成")
    return run


def _run_payload(run: DocumentParseRun) -> dict:
    import json

    return {
        "id": run.id, "asset_id": run.asset_id, "doc_type": run.doc_type,
        "status": run.status, "parser_name": run.parser_name,
        "parser_version": run.parser_version, "config_version": run.config_version,
        "is_current": run.is_current, "fingerprint": run.fingerprint,
        "page_count": run.page_count, "text_chars": run.text_chars,
        "quality_status": run.quality_status,
        "quality": QualityReport.from_dict(
            json.loads(run.quality_json or "{}")).to_dict(),
        "created_at": run.created_at, "started_at": run.started_at,
        "finished_at": run.finished_at, "error_code": run.error_code,
        "error_message": run.error_message,
    }


def _document_payload(db: Session, run: DocumentParseRun) -> dict:
    document = load_ir(db, run)
    pages = [{
        "page_number": page.page_number, "status": page.status,
        "extraction": page.extraction, "width": page.width, "height": page.height,
        "rotation": page.rotation, "confidence": page.confidence,
        "warnings": page.warnings, "text_chars": len(page.text.strip()),
        "render_url": f"/api/v1/assets/{run.asset_id}/document/pages/{page.page_number}/render",
    } for page in document.pages]
    sections = [{
        "section_id": section.section_id, "title": section.title, "level": section.level,
        "page_start": section.page_start, "page_end": section.page_end,
        "block_ids": section.block_ids,
    } for section in document.sections]
    return {"run": _run_payload(run), "pages": pages, "sections": sections}


def _block_payload(block) -> dict:
    return {
        "block_id": block.block_id, "page_number": block.page_number,
        "type": block.type, "level": block.level, "text": block.text,
        "latex": block.latex,
        "table": block.table.to_dict() if block.table else None,
        "figure": block.figure.to_dict() if block.figure else None,
        "bbox": block.bbox, "extraction": block.extraction,
        "confidence": block.confidence, "warnings": block.warnings,
    }


def _figure_image_url(asset_id: str, run_id: str, image_key: str) -> str:
    token = Path(image_key).name.rsplit(".", 1)[0]
    return f"/api/v1/assets/{asset_id}/document/figures/{token}?run_id={run_id}"


@router.get("/notebooks/{notebook_id}/assets/{asset_id}/processing-jobs",
            response_model=list[AssetProcessingJobRead])
def list_notebook_asset_jobs(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    try:
        assert_notebook_asset(db, asset_id, notebook_id)
    except AssetUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    return list(db.scalars(select(AssetProcessingJob).where(
        AssetProcessingJob.asset_id == asset_id,
        AssetProcessingJob.notebook_id == notebook_id,
    ).order_by(AssetProcessingJob.created_at.desc())).all())


@router.post("/assets/{asset_id}/parse-retries", response_model=AssetProcessingJobRead,
             status_code=202)
def retry_asset_parse(asset_id: str, db: Session = Depends(get_db)):
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id, NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    asset = db.get(Asset, asset_id)
    if owner is None or asset is None or asset.state != "ready" or asset.media_type != "image":
        raise HTTPException(404, "可重试的原始图片不存在")
    attempts = db.scalar(select(func.count(AssetProcessingJob.id)).where(
        AssetProcessingJob.asset_id == asset_id,
    )) or 0
    if attempts >= 5:
        raise HTTPException(409, "图片解析最多尝试 5 次；请先检查 OCR 配置或更换图片")
    active = db.scalar(select(AssetProcessingJob.id).where(
        AssetProcessingJob.asset_id == asset_id,
        AssetProcessingJob.status.in_(("pending", "processing")),
    ))
    if active:
        raise HTTPException(409, "图片解析任务已在队列中")
    job = AssetProcessingJob(
        asset_id=asset_id, notebook_id=owner.notebook_id, owner_link_id=owner.id,
        kind="image_parse",
        status="pending", attempt_count=0,
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


class CourseNotebookFileRead(BaseModel):
    id: str
    notebook_id: str | None
    notebook_title: str | None
    original_filename: str
    media_type: str
    size_bytes: int
    created_at: datetime
    status: str


class CourseNotebookFilesRead(BaseModel):
    course_id: str
    file_count: int
    total_size_bytes: int
    files: list[CourseNotebookFileRead]


@router.get("/courses/{course_id}/materials", response_model=list[MaterialRead])
def list_materials(course_id: str, db: Session = Depends(get_db)) -> list[Material]:
    ensure_course(db, course_id)
    return sorted(materials_for_course(db, course_id), key=lambda item: item.created_at,
                  reverse=True)


@router.get("/courses/{course_id}/notebook-files", response_model=CourseNotebookFilesRead)
def list_course_notebook_files(course_id: str, db: Session = Depends(get_db)) -> dict:
    """Aggregate uploaded source files and direct attachments across course notebooks."""
    ensure_course(db, course_id)
    notebooks = db.scalars(select(Notebook).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None)
    )).all()
    titles = {book.id: book.title for book in notebooks}
    files: list[dict] = []
    materials = sorted(materials_for_course(db, course_id), key=lambda item: item.created_at,
                       reverse=True)
    for item in materials:
        notebook_title = titles.get(item.notebook_id) if item.notebook_id else None
        files.append({
            "id": item.id, "notebook_id": item.notebook_id,
            "notebook_title": notebook_title,
            "original_filename": item.original_filename,
            "media_type": item.media_type or "application/octet-stream",
            "size_bytes": item.size_bytes, "created_at": item.created_at,
            "status": item.status,
        })
    notebook_assets = db.execute(select(Asset, NotebookAsset.notebook_id, NotebookAsset.role).join(
        NotebookAsset, NotebookAsset.asset_id == Asset.id,
    ).where(
        NotebookAsset.notebook_id.in_(titles), NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None), Asset.media_type == "image",
        Asset.state.in_(("ready", "missing", "quarantined")),
        NotebookAsset.role.in_(("source_material", "inline_image", "cover")),
    )).all()
    for asset, owner_notebook_id, _role in notebook_assets:
        files.append({
            "id": asset.id, "notebook_id": owner_notebook_id,
            "notebook_title": titles[owner_notebook_id],
            "original_filename": asset.original_name,
            "media_type": asset.mime_type, "size_bytes": asset.byte_size,
            "created_at": asset.created_at, "status": asset.state,
        })
    legacy_attachments = db.scalars(select(NotebookAttachment).where(
        NotebookAttachment.notebook_id.in_(titles),
        NotebookAttachment.asset_id.is_(None),
    )).all()
    for attachment in legacy_attachments:
        files.append({
            "id": attachment.id, "notebook_id": attachment.notebook_id,
            "notebook_title": titles[attachment.notebook_id],
            "original_filename": attachment.original_filename,
            "media_type": attachment.mime, "size_bytes": attachment.size_bytes,
            "created_at": attachment.created_at, "status": "legacy_unmapped",
        })
    files.sort(key=lambda item: item["created_at"], reverse=True)
    return {
        "course_id": course_id,
        "file_count": len(files),
        "total_size_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
    }



@router.get("/courses/{course_id}/deleted-materials", response_model=list[MaterialRead])
def list_deleted_materials(course_id: str, db: Session = Depends(get_db)) -> list[Material]:
    ensure_course(db, course_id)
    rows = materials_for_course(db, course_id, include_deleted=True)
    return sorted(
        [item for item in rows if item.deleted_at is not None],
        key=lambda item: item.deleted_at, reverse=True,
    )



@router.get("/materials/{material_id}/deletion-preview", response_model=DeletionPreview)
def preview_material_deletion(material_id: str, db: Session = Depends(get_db)) -> dict:
    material = ensure_material(db, material_id)
    return impact_preview(db, course_id=material_course_id(db, material), material_id=material.id)



@router.delete("/materials/{material_id}", response_model=DeletionPreview)
def delete_material(material_id: str, db: Session = Depends(get_db)) -> dict:
    material = ensure_material(db, material_id)
    try:
        return soft_delete_material(db, material)
    except DeletionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc



@router.post("/materials/{material_id}/restore", response_model=MaterialRead)
def restore_material(material_id: str, db: Session = Depends(get_db)) -> Material:
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is None:
        raise HTTPException(status_code=404, detail="待恢复资料不存在")
    course_id = material_course_id(db, material)
    if course_id is not None:
        ensure_course(db, course_id)
    material.deleted_at = None
    bump_order_revision(db, course_id, material.notebook_id)
    db.commit()
    db.refresh(material)
    return material



@router.post(
    "/courses/{course_id}/materials", response_model=UploadMaterialResponse, status_code=201
)
def upload_material(
    course_id: str,
    file: UploadFile = File(...),
    lecture_title: str = Form(...),
    topic_title: str = Form(default=""),
    allow_duplicate: bool = Form(default=False),
    notebook_id: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
) -> UploadMaterialResponse:
    ensure_course(db, course_id)
    batch = ensure_upload_batch(
        db, notebook_id, upload_batch_id, close_if_new=upload_batch_id is None,
    ) if notebook_id is not None else None
    try:
        material, job = ingest_document(
            db, course_id=course_id, source=file.file,
            filename=file.filename or "upload", lecture_title=lecture_title,
            topic_title=topic_title, media_type=file.content_type,
            allow_duplicate=allow_duplicate, idempotency_key=idempotency_key,
            notebook_id=notebook_id, upload_batch_id=batch.id if batch else None,
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if batch is not None and material.asset_id is not None:
        register_generation_input(
            db, notebook_id=batch.notebook_id, asset_id=material.asset_id, batch_id=batch.id,
            parse_kind="material", parse_job_id=job.id,
        )
        db.commit()
    return UploadMaterialResponse(material=material, job=job,
                                  upload_batch_id=batch.id if batch else None)


@router.get("/notebooks/{notebook_id}/files", response_model=list[MaterialRead])
def list_notebook_files(notebook_id: str, db: Session = Depends(get_db)) -> list[Material]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    return list(db.scalars(select(Material).where(
        Material.notebook_id == notebook_id, Material.deleted_at.is_(None)
    ).order_by(Material.created_at.desc())).all())


@router.post("/notebooks/{notebook_id}/files", response_model=UploadMaterialResponse,
             status_code=201)
def upload_notebook_file(
    notebook_id: str,
    file: UploadFile = File(...),
    lecture_title: str = Form(default=""),
    topic_title: str = Form(default=""),
    allow_duplicate: bool = Form(default=False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
) -> UploadMaterialResponse:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batch = ensure_upload_batch(
        db, notebook_id, upload_batch_id, close_if_new=upload_batch_id is None,
    )
    try:
        material, job = ingest_document(
            db, course_id=notebook.course_id, notebook_id=notebook.id,
            source=file.file, filename=file.filename or "upload",
            lecture_title=lecture_title or (file.filename or "资料"),
            topic_title=topic_title, media_type=file.content_type,
            allow_duplicate=allow_duplicate, idempotency_key=idempotency_key,
            upload_batch_id=batch.id,
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    register_generation_input(
        db, notebook_id=notebook.id, asset_id=material.asset_id, batch_id=batch.id,
        parse_kind="material", parse_job_id=job.id,
    )
    db.commit()
    return UploadMaterialResponse(material=material, job=job, upload_batch_id=batch.id)



@router.post("/materials/{material_id}/retry", response_model=JobRead, status_code=202)
def retry_material(material_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    material = ensure_material(db, material_id)
    if material.status != "failed":
        raise HTTPException(status_code=409, detail="只有解析失败的资料可以重试")
    if not (settings.originals_dir / material.stored_filename).is_file():
        raise HTTPException(status_code=410, detail="原始课件文件不存在，请重新上传")
    material.status = "pending"
    job = ProcessingJob(material_id=material.id, kind="parse_material")
    db.add(job)
    db.flush()
    if material.asset_id:
        input_row = db.scalar(select(NotebookGenerationInput).where(
            NotebookGenerationInput.asset_id == material.asset_id,
        ))
        if input_row is not None and input_row.status != "completed":
            input_row.parse_job_id = job.id
            input_row.status = "waiting_parse"
            input_row.retry_count += 1
            input_row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


@router.post("/materials/{material_id}/reparse", response_model=JobRead, status_code=202)
def reparse_material(material_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    material = ensure_material(db, material_id)
    active_job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.material_id == material_id,
            ProcessingJob.status.in_(["pending", "processing"]),
        )
        .limit(1)
    )
    if active_job is not None:
        raise HTTPException(status_code=409, detail="资料已有正在处理的任务")
    if not (settings.originals_dir / material.stored_filename).is_file():
        raise HTTPException(status_code=410, detail="原始课件文件不存在，请重新上传")
    material.status = "pending"
    job = ProcessingJob(material_id=material.id, kind="reparse_material")
    db.add(job)
    db.flush()
    if material.asset_id:
        input_row = db.scalar(select(NotebookGenerationInput).where(
            NotebookGenerationInput.asset_id == material.asset_id,
        ))
        if input_row is not None and input_row.status not in {"completed", "generating"}:
            input_row.parse_job_id = job.id
            input_row.status = "waiting_parse"
            input_row.retry_count += 1
            input_row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


@router.post("/materials/{material_id}/ocr", response_model=JobRead, status_code=202)
def request_material_ocr(material_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    material = ensure_material(db, material_id)
    if mineru_adapter.configured():
        if not mineru_adapter.availability()["available"]:
            raise HTTPException(501, "已选择 MinerU，但当前后端环境没有安装 MinerU")
        # MinerU performs OCR as part of the whole-document parse. It does not
        # require a separately installed PaddleOCR/Tesseract engine.
        return reparse_material(material_id, db)
    capability = ocr_status()
    if capability["status"] != "ready":
        raise HTTPException(
            status_code=501,
            detail=(
                "OCR 当前不可用：请启用 NOTEBOOK_OCR_ENABLED，并安装 PaddleOCR、RapidOCR "
                "或 Tesseract；原生 PDF 渲染需要 PyMuPDF 或 pypdfium2。"
            ),
        )
    active_job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.material_id == material_id,
            ProcessingJob.status.in_(["pending", "processing"]),
        )
        .limit(1)
    )
    if active_job is not None:
        raise HTTPException(status_code=409, detail="资料已有正在处理的任务")
    candidate = db.scalar(
        select(DocumentPage.id)
        .join(DocumentParseRun, DocumentParseRun.id == DocumentPage.parse_run_id)
        .where(
            DocumentParseRun.asset_id == (material.asset_id or material.id),
            DocumentParseRun.is_current.is_(True),
            DocumentPage.status == "needs_ocr",
        )
        .limit(1)
    )
    if candidate is None:
        candidate = db.scalar(
            select(MaterialPage.id)
            .where(
                MaterialPage.material_id == material_id,
                MaterialPage.is_active.is_(True),
                MaterialPage.parse_status == "ocr_candidate",
            )
            .limit(1)
        )
    if candidate is None:
        raise HTTPException(status_code=409, detail="当前资料没有待 OCR 的位置")
    material.status = "pending"
    job = ProcessingJob(material_id=material.id, kind="ocr_material")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job



@router.get("/materials/{material_id}/pages", response_model=list[PageRead])
def list_material_pages(material_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Legacy projection of the current Document IR for the materials page."""

    document, _run = _material_document(db, material_id)
    if document is None:
        return []
    return [_page_payload(page, material_id) for page in document.pages]


@router.get(
    "/materials/{material_id}/pages/{page_number}/evidence",
    response_model=PageEvidenceRead,
)
def get_page_evidence(
    material_id: str, page_number: int, db: Session = Depends(get_db)
) -> dict:
    document, run = _material_document(db, material_id)
    if document is None:
        raise HTTPException(status_code=404, detail="资料还没有完成的解析版本")
    page = next((item for item in document.pages if item.page_number == page_number), None)
    if page is None:
        raise HTTPException(status_code=404, detail="资料位置不存在")

    rows = list(db.scalars(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id,
    )).all())
    db_id_by_block = {row.block_id: row.id for row in rows}
    citations: dict[str, list[tuple[str, str]]] = {}
    links = db.execute(
        select(NotebookBlockSource.document_block_id, NotebookBlockSource.block_id,
               Notebook.id, Notebook.title, NotebookSection.heading)
        .join(Notebook, Notebook.id == NotebookBlockSource.notebook_id)
        .outerjoin(NotebookSection, (NotebookSection.notebook_id == NotebookBlockSource.notebook_id)
                   & (NotebookSection.block_id == NotebookBlockSource.block_id))
        .where(NotebookBlockSource.parse_run_id == run.id)
    ).all()
    for document_block_id, _body_block_id, notebook_id, title, heading in links:
        citations.setdefault(document_block_id, []).append(
            (notebook_id, heading or title),
        )
    blocks: list[dict] = []
    note_ids: list[str] = []
    note_titles: list[str] = []
    for block in sorted(page.blocks, key=lambda item: (item.order, item.global_order)):
        linked = citations.get(db_id_by_block.get(block.block_id, ""), [])
        block_note_ids = list(dict.fromkeys(item[0] for item in linked))
        block_note_titles = list(dict.fromkeys(item[1] for item in linked))
        for notebook_id in block_note_ids:
            if notebook_id not in note_ids:
                note_ids.append(notebook_id)
        for title in block_note_titles:
            if title not in note_titles:
                note_titles.append(title)
        blocks.append({
            "id": block.block_id,
            "page_id": page.page_id,
            "block_type": block.type,
            "content": block.text,
            "position": block.order,
            "font_size": None,
            "is_bold": False,
            "object_id": None,
            "location_label": block.source.location_label if block.source else None,
            "extraction_method": block.extraction,
            "confidence": block.confidence,
            "warning": "；".join(block.warnings) or None,
            "note_ids": block_note_ids,
            "note_titles": block_note_titles,
        })
    payload = _page_payload(page, material_id)
    payload.update({
        "blocks": blocks, "note_ids": note_ids, "note_titles": note_titles,
    })
    return payload


def _material_document(db: Session, material_id: str):
    material = ensure_material(db, material_id)
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_parse_run(db, asset.id) if asset is not None else None
    if run is None:
        return None, None
    return load_ir(db, run), run


def _page_payload(page, material_id: str = "") -> dict:
    heading = next(
        (block.text for block in sorted(page.blocks, key=lambda item: item.order)
         if block.type == "heading" and block.text.strip()), None,
    )
    status = "parsed"
    if page.status == "needs_ocr":
        status = "ocr_candidate"
    elif page.status in {"failed", "empty"}:
        status = page.status
    return {
        "id": page.page_id,
        "material_id": material_id,
        "page_number": page.page_number,
        "title": heading,
        "raw_text": page.text,
        "parse_status": status,
        "warning": "；".join(page.warnings) or None,
        "location_type": "page",
        "location_label": f"第 {page.page_number} 页",
        "stable_location_key": f"page:{page.page_number}",
        "extraction_method": page.extraction,
        "confidence": page.confidence,
    }


@router.get("/materials/{material_id}/coverage", response_model=CoverageRead)
def get_material_coverage(material_id: str, db: Session = Depends(get_db)) -> dict:
    ensure_material(db, material_id)
    return material_coverage(db, material_id)



@router.get("/materials/{material_id}/latest-job", response_model=JobRead)
def get_latest_material_job(material_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    ensure_material(db, material_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.material_id == material_id).order_by(ProcessingJob.created_at.desc()).limit(1))
    if job is None:
        raise HTTPException(status_code=404, detail="资料没有处理任务")
    return job



@router.get("/courses/{course_id}/web-sources", response_model=list[WebSourceRead])
def list_course_web_sources(course_id: str, db: Session = Depends(get_db)) -> list[WebSource]:
    ensure_course(db, course_id)
    return list(db.scalars(select(WebSource).where(WebSource.course_id == course_id).order_by(WebSource.retrieved_at.desc())).all())



@router.get("/materials/{material_id}/web-sources", response_model=list[WebSourceRead])
def list_material_web_sources(material_id: str, db: Session = Depends(get_db)) -> list[WebSource]:
    ensure_material(db, material_id)
    return list(db.scalars(select(WebSource).where(WebSource.material_id == material_id).order_by(WebSource.retrieved_at.desc())).all())
