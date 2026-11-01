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
    from app.document_processing.engines.vision import config_snapshot

    vision = config_snapshot()
    return {"model": settings.deepseek_model, "base_url": settings.deepseek_base_url,
            "timeout_seconds": settings.deepseek_timeout_seconds,
            "vision": vision,
            "vision_capability_fingerprint": _vision_fingerprint(vision),
            "prompt_version": "llm-document-v1"}


def ensure_vision_preflight() -> None:
    from app.document_processing.engines.vision import (
        VisionCapabilityError,
        require_image_capability,
    )

    try:
        require_image_capability()
        from app.services.processing_budget import ensure_budget_ready
        ensure_budget_ready("vision")
        ensure_budget_ready("text")
    except VisionCapabilityError as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _vision_fingerprint(config: dict) -> str:
    from app.document_processing.engines.vision import config_fingerprint

    return config_fingerprint(config)


def asset_config(asset) -> dict:
    return json.loads(asset.processing_config_json or "{}")


def provider_client(config: dict):
    from app.ai.deepseek import DeepSeekClient
    return DeepSeekClient(replace(settings,
        deepseek_model=config.get("model") or settings.deepseek_model,
        deepseek_base_url=config.get("base_url") or settings.deepseek_base_url,
        deepseek_timeout_seconds=config.get("timeout_seconds") or settings.deepseek_timeout_seconds))


def vision_client(config: dict, effective_vision: dict | None = None):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing.engines.vision import _settings

    vision = effective_vision or _settings(
        config.get("vision") if isinstance(config.get("vision"), dict) else None
    )
    return DeepSeekClient(replace(settings,
        deepseek_model=vision["model"] or "",
        deepseek_base_url=vision["base_url"] or "",
        deepseek_api_key=vision["api_key"] or None,
        deepseek_timeout_seconds=vision["timeout"]))
