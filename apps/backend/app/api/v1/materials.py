from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.shared import ensure_course, ensure_material
from app.core.config import settings
from app.db.database import get_db
from app.db.models import (
    Asset,
    AssetParseResult,
    AssetProcessingJob,
    Material,
    MaterialPage,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookGenerationInput,
    NotebookUploadBatch,
    PageBlock,
    ProcessingJob,
    SourceRef,
    WebSource,
)
from app.notes.assets import AssetUnavailable, assert_notebook_asset, remove_notebook_asset
from app.notes.notebook import bump_order_revision
from app.parsers.ocr import status as ocr_status
from app.schemas.api import (
    BlockRead,
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
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.role == "inline_image",
        NotebookAsset.detached_at.is_(None),
    ))
    if link is None:
        db.add(NotebookAsset(
            notebook_id=notebook_id, asset_id=asset_id, role="inline_image",
            is_owner=False,
        ))
        db.commit()
    return _asset_read(asset, "inline_image", notebook_id)


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
    notebook_ids = select(Notebook.id).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None)
    )
    return list(
        db.scalars(
            select(Material).outerjoin(Notebook, Notebook.id == Material.notebook_id)
            .where(or_(
                Material.course_id == course_id,
                and_(Material.notebook_id.in_(notebook_ids), Notebook.deleted_at.is_(None)),
            ), Material.deleted_at.is_(None))
            .order_by(Material.created_at.desc())
        ).all()
    )


@router.get("/courses/{course_id}/notebook-files", response_model=CourseNotebookFilesRead)
def list_course_notebook_files(course_id: str, db: Session = Depends(get_db)) -> dict:
    """Aggregate uploaded source files and direct attachments across course notebooks."""
    ensure_course(db, course_id)
    notebooks = db.scalars(select(Notebook).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None)
    )).all()
    titles = {book.id: book.title for book in notebooks}
    files: list[dict] = []
    materials = db.scalars(select(Material).outerjoin(
        Notebook, Notebook.id == Material.notebook_id,
    ).where(
        Material.deleted_at.is_(None),
        or_(
            Material.course_id == course_id,
            and_(Notebook.course_id == course_id, Notebook.deleted_at.is_(None)),
        ),
    )).all()
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
    return list(db.scalars(select(Material).outerjoin(Notebook, Notebook.id == Material.notebook_id).where(
        or_(Material.course_id == course_id,
            and_(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))),
        Material.deleted_at.is_not(None)
    ).order_by(Material.deleted_at.desc())).all())



@router.get("/materials/{material_id}/deletion-preview", response_model=DeletionPreview)
def preview_material_deletion(material_id: str, db: Session = Depends(get_db)) -> dict:
    material = ensure_material(db, material_id)
    return impact_preview(db, course_id=material.course_id, material_id=material.id)



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
    if material.course_id is not None:
        ensure_course(db, material.course_id)
    material.deleted_at = None
    bump_order_revision(db, material.course_id, material.notebook_id)
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
    capability = ocr_status()
    if capability["status"] != "ready":
        raise HTTPException(
            status_code=501,
            detail="OCR 当前不可用：请启用 NOTEBOOK_OCR_ENABLED，并安装 Tesseract、PyMuPDF 及其语言包。",
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
def list_material_pages(material_id: str, db: Session = Depends(get_db)) -> list[MaterialPage]:
    ensure_material(db, material_id)
    return list(
        db.scalars(
            select(MaterialPage)
            .where(MaterialPage.material_id == material_id, MaterialPage.is_active.is_(True))
            .order_by(MaterialPage.page_number)
        ).all()
    )


@router.get(
    "/materials/{material_id}/pages/{page_number}/evidence",
    response_model=PageEvidenceRead,
)
def get_page_evidence(
    material_id: str, page_number: int, db: Session = Depends(get_db)
) -> PageEvidenceRead:
    ensure_material(db, material_id)
    page = db.scalar(
        select(MaterialPage)
        .where(
            MaterialPage.material_id == material_id,
            MaterialPage.page_number == page_number,
            MaterialPage.is_active.is_(True),
        )
        .options(
            selectinload(MaterialPage.blocks)
            .selectinload(PageBlock.source_refs)
            .selectinload(SourceRef.notes)
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail="资料位置不存在")

    all_note_ids: set[str] = set()
    all_note_titles: dict[str, str] = {}
    blocks: list[BlockRead] = []
    for block in sorted(page.blocks, key=lambda item: item.position):
        block_note_titles: dict[str, str] = {}
        for source_ref in block.source_refs:
            if source_ref.status != "active":
                continue
            for note in source_ref.notes:
                block_note_titles[note.id] = note.title
        all_note_ids.update(block_note_titles)
        all_note_titles.update(block_note_titles)
        blocks.append(BlockRead(
            id=block.id,
            page_id=block.page_id,
            block_type=block.block_type,
            content=block.content,
            position=block.position,
            font_size=block.font_size,
            is_bold=block.is_bold,
            object_id=block.object_id,
            location_label=block.location_label,
            extraction_method=block.extraction_method,
            confidence=block.confidence,
            warning=block.warning,
            note_ids=sorted(block_note_titles),
            note_titles=[block_note_titles[key] for key in sorted(block_note_titles)],
        ))
    return PageEvidenceRead(
        id=page.id,
        material_id=page.material_id,
        page_number=page.page_number,
        title=page.title,
        raw_text=page.raw_text,
        parse_status=page.parse_status,
        warning=page.warning,
        location_type=page.location_type,
        location_label=page.location_label,
        stable_location_key=page.stable_location_key,
        extraction_method=page.extraction_method,
        confidence=page.confidence,
        blocks=blocks,
        note_ids=sorted(all_note_ids),
        note_titles=[all_note_titles[key] for key in sorted(all_note_titles)],
    )


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
