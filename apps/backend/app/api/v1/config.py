from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.service_checks import check_provider, provider_status, test_connectivity
from app.core.settings_store import (
    SettingsVerifyError,
    SettingsWriteError,
    apply_updates,
    build_status,
)
from app.db.database import get_db
from app.db.models import ProviderCall
from app.parsers.ocr import status as ocr_status
from app.schemas.api import (
    ProviderCallRead,
    ProviderConnectivityTestRequest,
    SettingsStatus,
    SettingsUpdate,
    SettingsUpdateResponse,
    VisionCapabilityTestRequest,
)
from app.services.provider_audit import begin_call, finish_call, provider_status_from_error

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "notebook-backend"}


@router.get("/settings", response_model=SettingsStatus)
def get_settings() -> SettingsStatus:
    return SettingsStatus.model_validate(build_status())


@router.patch("/settings", response_model=SettingsUpdateResponse)
def update_settings(
    payload: SettingsUpdate,
    x_notebook_settings_token: str | None = Header(default=None),
) -> SettingsUpdateResponse:
    try:
        outcome = apply_updates(payload.model_dump(exclude_none=True), x_notebook_settings_token)
    except SettingsVerifyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SettingsWriteError as exc:
        detail = str(exc)
        status = 403 if "口令" in detail or "密钥写入" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc
    return SettingsUpdateResponse(
        updated=outcome.updated,
        backup_path=outcome.backup_path,
        status=SettingsStatus.model_validate(build_status()),
        warnings=outcome.warnings,
    )



@router.get("/web-search/status")
def get_web_search_status() -> dict[str, str | bool]:
    state = provider_status("tavily")
    return {"configured": state["configured"], "provider": "Tavily", "status": state["status"]}



@router.get("/config/status")
def get_config_status() -> dict:
    result = {provider: provider_status(provider) for provider in ("deepseek", "embedding", "tavily")}
    result["ocr"] = ocr_status()
    return result


@router.get("/config/capabilities")
def get_capabilities() -> dict:
    from app.document_processing.routes import route_limits
    return {
        "allowed_extensions": list(settings.allowed_extensions),
        "max_upload_bytes": settings.max_upload_bytes,
        "max_pages": settings.max_pages,
        "ocr": ocr_status(),
        "default_processing_route": settings.document_processing_route,
        "processing_routes": {
            route: {"max_upload_bytes": route_limits(route)[0], "max_pages": route_limits(route)[1]}
            for route in ("standard", "llm")
        },
    }


@router.get("/ocr/status")
def get_ocr_status() -> dict:
    return ocr_status()



@router.post("/config/check/{provider}")
def check_config_provider(provider: str, db: Session = Depends(get_db)) -> dict:
    if provider == "ocr":
        return ocr_status()
    if provider not in ("deepseek", "embedding", "tavily"):
        raise HTTPException(status_code=404, detail="服务类型不存在")
    return check_provider(provider, db)


@router.post("/config/test-connectivity")
def test_api_connectivity(
    payload: ProviderConnectivityTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    """单项连通性测试：用请求中的草稿值（不落盘）独立验证某个 API。"""
    api_key = payload.api_key
    base_url = payload.base_url
    model = payload.model
    if api_key and len(api_key.strip()) < 8:
        raise HTTPException(status_code=422, detail="API Key 长度过短")
    if base_url and not base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="服务地址必须以 http:// 或 https:// 开头")
    if model and model.strip() and not model.strip().replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="模型名只能包含字母、数字和连字符")
    return test_connectivity(
        payload.provider,
        db,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


@router.post("/config/test-vision-capability")
def test_vision_image_capability(
    payload: VisionCapabilityTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Explicitly test image input with a tiny PNG; only metadata is audited."""
    from app.document_processing.engines.vision import preflight_image_support

    if payload.api_key and len(payload.api_key.strip()) < 8:
        raise HTTPException(status_code=422, detail="视觉 API Key 长度过短")
    if payload.base_url and not payload.base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="视觉服务地址必须以 http:// 或 https:// 开头")
    if payload.base_url:
        from urllib.parse import urlsplit
        parsed = urlsplit(payload.base_url.strip())
        if (not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise HTTPException(status_code=422, detail="视觉服务地址不能包含账号、密码、查询参数或片段")
    if payload.model and not all(char.isalnum() or char in "-_.:/" for char in payload.model):
        raise HTTPException(status_code=422, detail="视觉模型 ID 格式无效")
    config = {key: value for key, value in {
        "base_url": payload.base_url, "api_key": payload.api_key,
        "model": payload.model, "timeout_seconds": payload.timeout_seconds,
    }.items() if value is not None}
    audit, started = begin_call(
        db, provider="vision", operation="image_capability_preflight",
        model=payload.model, request_units=1,
        metadata={"has_base_url": bool(payload.base_url), "image_test": True},
    )
    db.commit()
    try:
        result = preflight_image_support(config)
    except Exception as exc:
        finish_call(db, audit, started, status=provider_status_from_error(exc),
                    error_type=type(exc).__name__)
        db.commit()
        raise HTTPException(status_code=502, detail="视觉模型预检失败") from exc
    finish_call(db, audit, started,
                status="success" if result.get("supports_image_input") else str(result.get("status") or "failed"),
                response_units=1 if result.get("supports_image_input") else 0)
    db.commit()
    return result


@router.get("/config/diagnostics")
def get_diagnostics(db: Session = Depends(get_db)) -> dict:
    """Return actionable local capability state without exposing environment secrets."""
    return {
        "data_dir": str(settings.data_dir),
        "database": str(settings.data_dir / "notebook.sqlite3"),
        "originals_dir": str(settings.originals_dir),
        "providers": get_config_status(),
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_pages": settings.max_pages,
            "allowed_extensions": list(settings.allowed_extensions),
        },
        "security": {
            "bind_address": "127.0.0.1 (configured by local dev script)",
            "secrets_in_response": False,
            "backup_excludes_env": True,
        },
        "provider_calls": _provider_call_summary(db),
    }


def _provider_call_summary(db: Session, limit: int = 20) -> list[dict]:
    calls = list(db.scalars(
        select(ProviderCall)
        .order_by(ProviderCall.created_at.desc())
        .limit(limit)
    ).all())
    return [ProviderCallRead.model_validate(call).model_dump(mode="json") for call in calls]


@router.get("/config/provider-calls", response_model=list[ProviderCallRead])
def list_provider_calls(limit: int = 50, db: Session = Depends(get_db)) -> list[ProviderCall]:
    bounded_limit = max(1, min(limit, 200))
    return list(db.scalars(
        select(ProviderCall)
        .order_by(ProviderCall.created_at.desc())
        .limit(bounded_limit)
    ).all())
