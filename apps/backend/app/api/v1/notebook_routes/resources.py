"""Notebook file upload/download HTTP adapters."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.notes.attachments import MAX_ATTACHMENT_BYTES, public_url
from app.schemas.notebook import NotebookAttachmentRead
from app.services.notebook_resources import (
    create_notebook_attachment,
    get_notebook_asset_content,
    replace_notebook_cover,
)
from app.services.notebook_resources import (
    delete_notebook_cover as delete_notebook_cover_service,
)
from app.services.notebook_resources import (
    get_notebook_attachment as get_notebook_attachment_service,
)
from app.services.notebook_resources import (
    get_notebook_cover as get_notebook_cover_service,
)

from .common import _cover_url

router = APIRouter()


@router.put("/notebooks/{notebook_id}/cover")
async def upload_notebook_cover(notebook_id: str, file: UploadFile = File(...),
                                db: Session = Depends(get_db)):
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    book = replace_notebook_cover(
        db, notebook_id, filename=file.filename or "cover", data=data,
    )
    return {"cover_url": _cover_url(book)}


@router.get("/notebooks/{notebook_id}/cover")
def get_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
    path, media_type = get_notebook_cover_service(db, notebook_id)
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/notebooks/{notebook_id}/cover", status_code=204)
def delete_notebook_cover(notebook_id: str, db: Session = Depends(get_db)):
    delete_notebook_cover_service(db, notebook_id)


@router.post("/courses/{course_id}/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_notebook_attachment(course_id: str, notebook_id: str,
                                     file: UploadFile = File(...),
                                     db: Session = Depends(get_db)):
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    attachment = create_notebook_attachment(
        db, notebook_id, course_id=course_id,
        filename=file.filename or "image", data=data,
    )
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}


@router.post("/notebooks/{notebook_id}/attachments",
             response_model=NotebookAttachmentRead, status_code=201)
async def upload_unbound_notebook_attachment(notebook_id: str,
                                             file: UploadFile = File(...),
                                             db: Session = Depends(get_db)):
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    attachment = create_notebook_attachment(
        db, notebook_id, unbound=True, filename=file.filename or "image", data=data,
    )
    return {"id": attachment.id, "url": public_url(attachment.id),
            "original_filename": attachment.original_filename, "mime": attachment.mime,
            "size_bytes": attachment.size_bytes, "created_at": attachment.created_at}


@router.get("/notebook-attachments/{attachment_id}")
def get_notebook_attachment(attachment_id: str, db: Session = Depends(get_db)):
    path, media_type = get_notebook_attachment_service(db, attachment_id)
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})


@router.get("/assets/{asset_id}/content")
@router.get("/notebooks/{notebook_id}/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db),
):
    path, media_type = get_notebook_asset_content(db, asset_id, notebook_id)
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})
