"""Assets HTTP routes and helpers."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.material_routes.common import asset_read as _asset_read
from app.db.database import get_db
from app.schemas.assets import AssetRead
from app.services.notebook_resources import (
    delete_notebook_asset as delete_notebook_asset_service,
)
from app.services.notebook_resources import list_notebook_assets as list_notebook_assets_service
from app.services.notebook_resources import (
    mark_notebook_asset_inline,
)
from app.services.notebook_resources import (
    restore_notebook_asset as restore_notebook_asset_service,
)

router = APIRouter()




@router.get("/notebooks/{notebook_id}/assets", response_model=list[AssetRead])
def list_notebook_assets(notebook_id: str, db: Session = Depends(get_db)):
    rows = list_notebook_assets_service(db, notebook_id)
    return [_asset_read(asset, role, owner_notebook_id) for asset, role, owner_notebook_id in rows]


@router.get("/notebooks/{notebook_id}/detached-assets", response_model=list[AssetRead])
def list_detached_notebook_assets(notebook_id: str, db: Session = Depends(get_db)):
    rows = list_notebook_assets_service(db, notebook_id, detached=True)
    return [_asset_read(asset, role, owner_notebook_id) for asset, role, owner_notebook_id in rows]

@router.post("/notebooks/{notebook_id}/assets/{asset_id}/restore", response_model=AssetRead)
def restore_notebook_asset(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    asset, role = restore_notebook_asset_service(db, notebook_id, asset_id)
    return _asset_read(asset, role, notebook_id)


@router.post("/notebooks/{notebook_id}/assets/{asset_id}/inline", response_model=AssetRead)
def mark_asset_inline(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    asset, role = mark_notebook_asset_inline(db, notebook_id, asset_id)
    return _asset_read(asset, role, notebook_id)


@router.delete("/notebooks/{notebook_id}/assets/{asset_id}")
def delete_notebook_asset(notebook_id: str, asset_id: str, db: Session = Depends(get_db)):
    state = delete_notebook_asset_service(db, notebook_id, asset_id)
    return {"asset_id": asset_id, "state": state}

