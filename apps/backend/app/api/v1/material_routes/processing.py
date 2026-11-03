"""HTTP adapters for Material and Asset processing operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.material_routes.documents import _ensure_asset
from app.db.database import get_db
from app.db.models import AssetProcessingJob
from app.notes.assets import AssetUnavailable, assert_notebook_asset
from app.schemas.api import JobRead
from app.schemas.assets import AssetProcessingJobRead
from app.services.asset_processing import (
    cancel_asset_processing,
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
from app.services.errors import ApplicationError
from app.services.processing_budget import budget_read

router = APIRouter()


class ProcessingRouteSelection(BaseModel):
    processing_route: str


def _http_error(exc: ApplicationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/materials/{material_id}/retry", response_model=JobRead, status_code=202)
def retry_material(material_id: str, db: Session = Depends(get_db)):
    try:
        return retry_material_parse(db, material_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.post("/materials/{material_id}/reparse", response_model=JobRead, status_code=202)
def reparse_material_route(material_id: str, db: Session = Depends(get_db)):
    try:
        return reparse_material_service(db, material_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.post("/materials/{material_id}/ocr", response_model=JobRead, status_code=202)
def request_material_ocr_route(material_id: str, db: Session = Depends(get_db)):
    try:
        return request_material_ocr_service(db, material_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.post("/assets/{asset_id}/processing-route", status_code=202)
def switch_asset_processing_route_route(
    asset_id: str, payload: ProcessingRouteSelection, db: Session = Depends(get_db),
):
    try:
        return switch_asset_processing_route(db, asset_id, payload.processing_route)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.post("/assets/{asset_id}/cancel-processing")
def cancel_asset_processing_route(asset_id: str, db: Session = Depends(get_db)):
    try:
        return cancel_asset_processing(db, asset_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/assets/{asset_id}/parse-retries",
    response_model=AssetProcessingJobRead,
    status_code=202,
)
def retry_asset_parse_route(asset_id: str, db: Session = Depends(get_db)):
    try:
        return retry_asset_parse(db, asset_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc


@router.get("/assets/{asset_id}/processing-budget")
def get_asset_processing_budget(
    asset_id: str, notebook_id: str | None = None, db: Session = Depends(get_db),
):
    _ensure_asset(db, asset_id, notebook_id)
    return budget_read(asset_id) or {
        "asset_id": asset_id, "currency": "CNY", "limit_fen": 1000,
        "settled_fen": 0, "reserved_fen": 0, "remaining_fen": 1000,
        "status": "active", "reservations": [],
    }


@router.get(
    "/notebooks/{notebook_id}/assets/{asset_id}/processing-jobs",
    response_model=list[AssetProcessingJobRead],
)
def list_notebook_asset_jobs(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    try:
        assert_notebook_asset(db, asset_id, notebook_id)
    except AssetUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    return list(db.scalars(select(AssetProcessingJob).where(
        AssetProcessingJob.asset_id == asset_id,
        AssetProcessingJob.notebook_id == notebook_id,
    ).order_by(AssetProcessingJob.created_at.desc())).all())
