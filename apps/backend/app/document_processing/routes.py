"""Backward-compatible imports for document processing configuration.

New code should import these helpers from ``document_processing.config``.
"""
from app.document_processing.config import (
    asset_config,
    ensure_vision_preflight,
    provider_client,
    provider_snapshot,
    resolve_route,
    route_limits,
    vision_client,
)

__all__ = [
    "asset_config", "ensure_vision_preflight", "provider_client",
    "provider_snapshot", "resolve_route", "route_limits", "vision_client",
]
