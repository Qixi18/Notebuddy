"""Compatibility router composing the Material HTTP subroutes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.material_routes.assets import router as assets_router
from app.api.v1.material_routes.documents import (
    _document_payload,
    get_asset_document,
    get_document_coverage,
)
from app.api.v1.material_routes.documents import (
    router as documents_router,
)
from app.api.v1.material_routes.materials import router as materials_router
from app.api.v1.material_routes.processing import (
    ProcessingRouteSelection,
)
from app.api.v1.material_routes.processing import (
    router as processing_router,
)
from app.api.v1.material_routes.uploads import router as uploads_router
from app.db.models import ProcessingJob
from app.document_processing.adapters import mineru as mineru_adapter
from app.services.asset_processing import (
    reparse_material as reparse_material_service,
)
from app.services.asset_processing import (
    request_material_ocr as request_material_ocr_service,
)
from app.services.asset_processing import (
    retry_material_parse,
)
from app.services.asset_processing import (
    switch_asset_processing_route as switch_asset_processing_route_service,
)
from app.services.errors import ApplicationError

__all__ = [
    "ProcessingRouteSelection",
    "_document_payload",
    "get_asset_document",
    "get_document_coverage",
    "mineru_adapter",
    "reparse_material",
    "request_material_ocr",
    "retry_material",
    "router",
    "switch_asset_processing_route",
]

router = APIRouter()
for child_router in (assets_router, documents_router, processing_router, materials_router, uploads_router):
    router.include_router(child_router)


def retry_material(material_id: str, db: Session) -> ProcessingJob:
    return retry_material_parse(db, material_id)


def reparse_material(material_id: str, db: Session) -> ProcessingJob:
    return reparse_material_service(db, material_id)


def request_material_ocr(material_id: str, db: Session) -> ProcessingJob:
    return request_material_ocr_service(db, material_id)


def switch_asset_processing_route(
    asset_id: str, payload: ProcessingRouteSelection, db: Session,
) -> dict[str, str]:
    """Compatibility callable; the registered endpoint lives in material_routes.processing."""
    try:
        return switch_asset_processing_route_service(db, asset_id, payload.processing_route)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
