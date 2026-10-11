from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.shared import ensure_course, ensure_material
from app.core.config import settings
from app.db.database import get_db
from app.db.models import (
    Material,
    MaterialPage,
    PageBlock,
    ProcessingJob,
    SourceRef,
    WebSource,
)
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
from app.services.coverage import material_coverage
from app.services.deletion import (
    DeletionConflict,
    impact_preview,
    soft_delete_material,
)
from app.services.uploads import UploadRejected, ingest_document

router = APIRouter()


@router.get("/courses/{course_id}/materials", response_model=list[MaterialRead])
def list_materials(course_id: str, db: Session = Depends(get_db)) -> list[Material]:
    ensure_course(db, course_id)
    return list(
        db.scalars(
            select(Material)
            .where(Material.course_id == course_id, Material.deleted_at.is_(None))
            .order_by(Material.created_at.desc())
        ).all()
    )



@router.get("/courses/{course_id}/deleted-materials", response_model=list[MaterialRead])
def list_deleted_materials(course_id: str, db: Session = Depends(get_db)) -> list[Material]:
    ensure_course(db, course_id)
    return list(db.scalars(select(Material).where(
        Material.course_id == course_id, Material.deleted_at.is_not(None)
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
    ensure_course(db, material.course_id)
    material.deleted_at = None
    bump_order_revision(db, material.course_id)
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> UploadMaterialResponse:
    ensure_course(db, course_id)
    try:
        material, job = ingest_document(
            db, course_id=course_id, source=file.file,
            filename=file.filename or "upload", lecture_title=lecture_title,
            topic_title=topic_title, media_type=file.content_type,
            allow_duplicate=allow_duplicate, idempotency_key=idempotency_key,
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return UploadMaterialResponse(material=material, job=job)



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
