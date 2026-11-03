"""HTTP adapters for source uploads and Notebook upload batches."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.material_routes.common import asset_read
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Notebook, NotebookUploadBatch
from app.schemas.api import UploadMaterialResponse
from app.schemas.assets import AssetUploadRead
from app.services.asset_uploads import (
    upload_course_material,
    upload_notebook_asset,
    upload_notebook_file,
)
from app.services.errors import ApplicationError
from app.services.notebook_generation_inputs import (
    batch_status,
    close_upload_batch,
)

router = APIRouter()


def _http_error(exc: ApplicationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/notebooks/{notebook_id}/assets", response_model=AssetUploadRead, status_code=201)
async def upload_notebook_asset_route(
    notebook_id: str,
    file: UploadFile = File(...),
    processing_route: str | None = Form(default=None),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
):
    filename = file.filename or "upload"
    is_document = Path(filename).suffix.lower() in settings.allowed_extensions
    image_data = None if is_document else await file.read(20 * 1024 * 1024 + 1)
    try:
        result = upload_notebook_asset(
            db, notebook_id=notebook_id, filename=filename, source=file.file,
            image_data=image_data, media_type=file.content_type,
            upload_batch_id=upload_batch_id, processing_route=processing_route,
        )
    except ApplicationError as exc:
        raise _http_error(exc) from exc
    job = result.job
    return {
        "asset": asset_read(result.asset, "source_material", notebook_id),
        "upload_batch_id": result.upload_batch_id,
        "processing_job": ({
            "id": job.id, "asset_id": job.asset_id, "status": job.status,
            "attempt_count": job.attempt_count, "error_code": job.error_code,
            "error_message": job.error_message, "created_at": job.created_at,
            "finished_at": job.finished_at,
        } if job else None),
    }


@router.post("/notebooks/{notebook_id}/upload-batches/{batch_id}/complete")
def complete_notebook_upload_batch(
    notebook_id: str, batch_id: str, db: Session = Depends(get_db),
):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    try:
        batch = close_upload_batch(db, notebook_id, batch_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc
    return batch_status(db, batch)


@router.get("/notebooks/{notebook_id}/upload-batches/{batch_id}")
def get_notebook_upload_batch(
    notebook_id: str, batch_id: str, db: Session = Depends(get_db),
):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batch = db.get(NotebookUploadBatch, batch_id)
    if batch is None or batch.notebook_id != notebook_id:
        raise HTTPException(404, "上传批次不存在")
    return batch_status(db, batch)


@router.get("/notebooks/{notebook_id}/upload-batches")
def list_notebook_upload_batches(notebook_id: str, db: Session = Depends(get_db)):
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    batches = db.scalars(select(NotebookUploadBatch).where(
        NotebookUploadBatch.notebook_id == notebook_id,
    ).order_by(NotebookUploadBatch.created_at.desc()).limit(30)).all()
    return [batch_status(db, batch) for batch in batches]


@router.post("/courses/{course_id}/materials", response_model=UploadMaterialResponse, status_code=201)
def upload_material_route(
    course_id: str,
    file: UploadFile = File(...),
    lecture_title: str = Form(...),
    topic_title: str = Form(default=""),
    allow_duplicate: bool = Form(default=False),
    notebook_id: str | None = Form(default=None),
    processing_route: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
) -> UploadMaterialResponse:
    try:
        result = upload_course_material(
            db, course_id=course_id, source=file.file,
            filename=file.filename or "upload", lecture_title=lecture_title,
            topic_title=topic_title, media_type=file.content_type,
            notebook_id=notebook_id, allow_duplicate=allow_duplicate,
            idempotency_key=idempotency_key, upload_batch_id=upload_batch_id,
            processing_route=processing_route,
        )
    except ApplicationError as exc:
        raise _http_error(exc) from exc
    return UploadMaterialResponse(
        material=result.material, job=result.job,
        upload_batch_id=result.upload_batch_id,
    )


@router.post(
    "/notebooks/{notebook_id}/files",
    response_model=UploadMaterialResponse,
    status_code=201,
)
def upload_notebook_file_route(
    notebook_id: str,
    file: UploadFile = File(...),
    lecture_title: str = Form(default=""),
    topic_title: str = Form(default=""),
    allow_duplicate: bool = Form(default=False),
    processing_route: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    upload_batch_id: str | None = Header(default=None, alias="X-Upload-Batch-ID"),
    db: Session = Depends(get_db),
) -> UploadMaterialResponse:
    filename = file.filename or "upload"
    try:
        result = upload_notebook_file(
            db, notebook_id=notebook_id, source=file.file, filename=filename,
            lecture_title=lecture_title or filename or "资料", topic_title=topic_title,
            media_type=file.content_type, allow_duplicate=allow_duplicate,
            idempotency_key=idempotency_key, upload_batch_id=upload_batch_id,
            processing_route=processing_route,
        )
    except ApplicationError as exc:
        raise _http_error(exc) from exc
    return UploadMaterialResponse(
        material=result.material, job=result.job,
        upload_batch_id=result.upload_batch_id,
    )
