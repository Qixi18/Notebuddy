"""Materials HTTP routes and helpers."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course, ensure_material
from app.db.database import get_db
from app.db.models import (
    Asset,
    DocumentBlock,
    Material,
    Notebook,
    NotebookAsset,
    NotebookAttachment,
    NotebookBlockSource,
    NotebookSection,
    ProcessingJob,
    WebSource,
)
from app.document_processing.service import (
    current_run as current_parse_run,
)
from app.document_processing.service import (
    load_ir,
)
from app.schemas.api import (
    CoverageRead,
    DeletionPreview,
    JobRead,
    MaterialRead,
    PageEvidenceRead,
    PageRead,
    WebSourceRead,
)
from app.services.course_scope import material_course_id, materials_for_course
from app.services.coverage import material_coverage
from app.services.deletion import (
    DeletionConflict,
    impact_preview,
    soft_delete_material,
)
from app.services.deletion import (
    restore_material as restore_material_service,
)
from app.services.errors import ApplicationError

router = APIRouter()


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
    try:
        return restore_material_service(db, material_id)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/notebooks/{notebook_id}/files", response_model=list[MaterialRead])
def list_notebook_files(notebook_id: str, db: Session = Depends(get_db)) -> list[Material]:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    return list(db.scalars(select(Material).where(
        Material.notebook_id == notebook_id, Material.deleted_at.is_(None)
    ).order_by(Material.created_at.desc())).all())


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
