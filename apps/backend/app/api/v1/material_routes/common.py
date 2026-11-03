"""Small response helpers shared by Material route modules."""

from app.db.models import Asset


def asset_read(asset: Asset, role: str, notebook_id: str) -> dict:
    return {
        "id": asset.id,
        "source_type": asset.source_type,
        "media_type": asset.media_type,
        "mime_type": asset.mime_type,
        "original_name": asset.original_name,
        "byte_size": asset.byte_size,
        "sha256": asset.sha256,
        "state": asset.state,
        "role": role,
        "content_url": f"/api/v1/notebooks/{notebook_id}/assets/{asset.id}/content",
        "created_at": asset.created_at,
        "processing_route": asset.processing_route,
    }
