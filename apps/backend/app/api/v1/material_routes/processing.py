"""HTTP adapters for Material and Asset processing operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.api import JobRead
from app.schemas.assets import AssetProcessingJobRead
from app.services.asset_processing import (
    cancel_asset_processing,
    list_notebook_asset_processing_jobs,
    read_asset_processing_budget,
    retry_asset_parse,
    retry_material_parse,
    switch_asset_processing_route,
)
from app.services.asset_processing import (
    reparse_material as reparse_material_service,
)
from app.services.asset_processing import (
    request_material_ocr as request_material_ocr_service,
)

router = APIRouter()


class ProcessingRouteSelection(BaseModel):
    processing_route: str


@router.post("/materials/{material_id}/retry", response_model=JobRead, status_code=202)
def retry_material(material_id: str, db: Session = Depends(get_db)):
    return retry_material_parse(db, material_id)


@router.post("/materials/{material_id}/reparse", response_model=JobRead, status_code=202)
def reparse_material_route(material_id: str, db: Session = Depends(get_db)):
    return reparse_material_service(db, material_id)


@router.post("/materials/{material_id}/ocr", response_model=JobRead, status_code=202)
def request_material_ocr_route(material_id: str, db: Session = Depends(get_db)):
    return request_material_ocr_service(db, material_id)


@router.post("/assets/{asset_id}/processing-route", status_code=202)
def switch_asset_processing_route_route(
    asset_id: str, payload: ProcessingRouteSelection, db: Session = Depends(get_db),
):
    return switch_asset_processing_route(db, asset_id, payload.processing_route)


@router.post("/assets/{asset_id}/cancel-processing")
def cancel_asset_processing_route(asset_id: str, db: Session = Depends(get_db)):
    return cancel_asset_processing(db, asset_id)


@router.post(
    "/assets/{asset_id}/parse-retries",
    response_model=AssetProcessingJobRead,
    status_code=202,
)
def retry_asset_parse_route(asset_id: str, db: Session = Depends(get_db)):
    return retry_asset_parse(db, asset_id)


@router.get("/assets/{asset_id}/processing-budget")
def get_asset_processing_budget(
    asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db),
):
    return read_asset_processing_budget(db, asset_id, notebook_id)


@router.get(
    "/notebooks/{notebook_id}/assets/{asset_id}/processing-jobs",
    response_model=list[AssetProcessingJobRead],
)
def list_notebook_asset_jobs(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    return list_notebook_asset_processing_jobs(db, notebook_id, asset_id)
