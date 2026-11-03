"""Material HTTP adapters; queries and compatibility projections live in services."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_material
from app.db.database import get_db
from app.db.models import Material, WebSource
from app.schemas.api import (
    CoverageRead,
    DeletionPreview,
    JobRead,
    MaterialRead,
    PageEvidenceRead,
    PageRead,
    WebSourceRead,
)
from app.services.coverage import material_coverage
from app.services.deletion import restore_material as restore_material_service
from app.services.deletion import soft_delete_material
from app.services.document_reads import (
    get_legacy_material_page_evidence,
    get_legacy_material_pages,
)
from app.services.material_reads import (
    get_latest_material_job as get_latest_material_job_service,
)
from app.services.material_reads import (
    list_course_materials,
    list_notebook_materials,
)
from app.services.material_reads import (
    list_course_notebook_files as list_course_notebook_files_service,
)
from app.services.material_reads import (
    list_course_web_sources as list_course_web_sources_service,
)
from app.services.material_reads import (
    list_deleted_materials as list_deleted_materials_service,
)
from app.services.material_reads import (
    list_material_web_sources as list_material_web_sources_service,
)
from app.services.material_reads import (
    preview_material_deletion as preview_material_deletion_service,
)

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
    return list_course_materials(db, course_id)


@router.get("/courses/{course_id}/notebook-files", response_model=CourseNotebookFilesRead)
def list_course_notebook_files(course_id: str, db: Session = Depends(get_db)) -> dict:
    return list_course_notebook_files_service(db, course_id)


@router.get("/courses/{course_id}/deleted-materials", response_model=list[MaterialRead])
def list_deleted_materials(course_id: str, db: Session = Depends(get_db)) -> list[Material]:
    return list_deleted_materials_service(db, course_id)


@router.get("/materials/{material_id}/deletion-preview", response_model=DeletionPreview)
def preview_material_deletion(material_id: str, db: Session = Depends(get_db)) -> dict:
    return preview_material_deletion_service(db, material_id)


@router.delete("/materials/{material_id}", response_model=DeletionPreview)
def delete_material(material_id: str, db: Session = Depends(get_db)) -> dict:
    return soft_delete_material(db, ensure_material(db, material_id))


@router.post("/materials/{material_id}/restore", response_model=MaterialRead)
def restore_material(material_id: str, db: Session = Depends(get_db)) -> Material:
    return restore_material_service(db, material_id)


@router.get("/notebooks/{notebook_id}/files", response_model=list[MaterialRead])
def list_notebook_files(notebook_id: str, db: Session = Depends(get_db)) -> list[Material]:
    return list_notebook_materials(db, notebook_id)


@router.get("/materials/{material_id}/pages", response_model=list[PageRead])
def list_material_pages(material_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return get_legacy_material_pages(db, material_id)


@router.get("/materials/{material_id}/pages/{page_number}/evidence",
            response_model=PageEvidenceRead)
def get_page_evidence(material_id: str, page_number: int,
                      db: Session = Depends(get_db)) -> dict:
    return get_legacy_material_page_evidence(db, material_id, page_number)


@router.get("/materials/{material_id}/coverage", response_model=CoverageRead)
def get_material_coverage(material_id: str, db: Session = Depends(get_db)) -> dict:
    return material_coverage(db, material_id)


@router.get("/materials/{material_id}/latest-job", response_model=JobRead)
def get_latest_material_job(material_id: str, db: Session = Depends(get_db)) -> JobRead:
    return get_latest_material_job_service(db, material_id)


@router.get("/courses/{course_id}/web-sources", response_model=list[WebSourceRead])
def list_course_web_sources(course_id: str, db: Session = Depends(get_db)) -> list[WebSource]:
    return list_course_web_sources_service(db, course_id)


@router.get("/materials/{material_id}/web-sources", response_model=list[WebSourceRead])
def list_material_web_sources(material_id: str, db: Session = Depends(get_db)) -> list[WebSource]:
    return list_material_web_sources_service(db, material_id)
