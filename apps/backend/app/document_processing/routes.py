"""Route admission and non-secret provider identity, frozen on each upload."""
from __future__ import annotations

import json
from dataclasses import replace

from app.core.config import settings


def resolve_route(value: str | None) -> str:
    route = value if isinstance(value, str) else settings.document_processing_route
    if route not in {"standard", "llm"}:
        raise ValueError("处理路线仅支持 standard 或 llm")
    return route


def route_limits(route: str) -> tuple[int, int]:
    if route == "llm":
        return settings.llm_max_upload_bytes, settings.llm_max_pages
    return settings.max_upload_bytes, settings.max_pages


def provider_snapshot() -> dict:
    return {"model": settings.deepseek_model, "base_url": settings.deepseek_base_url,
            "timeout_seconds": settings.deepseek_timeout_seconds,
            "prompt_version": "llm-document-v1"}


def asset_config(asset) -> dict:
    return json.loads(asset.processing_config_json or "{}")


def provider_client(config: dict):
    from app.ai.deepseek import DeepSeekClient
    return DeepSeekClient(replace(settings,
        deepseek_model=config.get("model") or settings.deepseek_model,
        deepseek_base_url=config.get("base_url") or settings.deepseek_base_url,
        deepseek_timeout_seconds=config.get("timeout_seconds") or settings.deepseek_timeout_seconds))
