"""Explicit, bounded checks for optional external providers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.ai.deepseek import DeepSeekClient
from app.core.config import settings
from app.retrieval.embedding import EmbeddingClient
from app.services.provider_audit import begin_call, finish_call, provider_status_from_error
from app.web_search.tavily import search

LAST_RESULTS: dict[str, dict] = {}
MIN_INTERVAL = timedelta(minutes=1)


def _configured(provider: str) -> bool:
    if provider == "deepseek":
        return DeepSeekClient().configured
    if provider == "embedding":
        return EmbeddingClient().configured
    if provider == "tavily":
        return bool(settings.tavily_api_key)
    raise ValueError("Unknown provider")


def provider_status(provider: str) -> dict:
    configured = _configured(provider)
    result = LAST_RESULTS.get(provider) if configured else None
    return {
        "provider": provider,
        "configured": configured,
        "status": result["status"] if result else ("configured_untested" if configured else "unconfigured"),
        "checked_at": result["checked_at"] if result else None,
    }


def _error_status(exc: Exception) -> str:
    cause = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        code = cause.response.status_code
        if code in (401, 403):
            return "authentication_failed"
        if code == 429:
            return "rate_limited"
    if isinstance(cause, httpx.TimeoutException):
        return "timeout"
    return "unavailable"


def _error_message(provider: str, exc: Exception, base_url: str | None) -> str:
    cause = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        code = cause.response.status_code
        if code in (401, 403):
            return f"API Key 被服务端拒绝（HTTP {code}），请检查密钥是否有效"
        if code == 429:
            return "触发服务端限流（HTTP 429），请稍后再试"
        return f"服务端返回 HTTP {code}"
    if isinstance(cause, httpx.TimeoutException):
        return f"连接超时（{base_url or '默认地址'}）"
    if isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout)):
        return f"无法连接服务地址（{base_url or '默认地址'}）"
    detail = getattr(cause, "args", None)
    if detail:
        text = str(detail[0]) if detail and detail[0] else "未知错误"
        if provider == "deepseek":
            prefix = "DeepSeek 调用失败"
        else:
            prefix = "Embedding 调用失败"
        return f"{prefix}：{text[:120]}"
    return "测试失败，请检查配置"


def check_provider(provider: str, db: Session | None = None) -> dict:
    if not _configured(provider):
        return provider_status(provider)
    now = datetime.now(UTC)
    prior = LAST_RESULTS.get(provider)
    if prior and now - prior["checked_at"] < MIN_INTERVAL:
        return provider_status(provider)
    audit = None
    started = None
    if db is not None:
        audit, started = begin_call(
            db,
            provider=provider,
            operation="connectivity_check",
            model=(settings.deepseek_model if provider == "deepseek" else settings.embedding_model if provider == "embedding" else "tavily-basic"),
            request_units=1,
        )
    try:
        if provider == "deepseek":
            DeepSeekClient().complete([{"role": "user", "content": "请回复 OK"}], max_tokens=8)
        elif provider == "embedding":
            EmbeddingClient().embed(["连接测试"])
        else:
            search("learning", max_results=1)
        status = "connected"
    except Exception as exc:
        status = _error_status(exc)
        if audit is not None and started is not None:
            finish_call(
                db,
                audit,
                started,
                status=provider_status_from_error(exc),
                error_type=type(exc).__name__,
            )
    else:
        if audit is not None and started is not None:
            finish_call(db, audit, started, status="success", response_units=1)
    LAST_RESULTS[provider] = {"status": status, "checked_at": now}
    return provider_status(provider)


def test_connectivity(
    provider: str,
    db: Session | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """单项连通性测试：使用面板草稿值（不落盘），各 API 相互独立。

    未提供的字段回退到已保存配置；连所需要字段都不齐全时直接返回
    `unconfigured`，不会影响其他 API 的测试。
    """
    if provider == "deepseek":
        effective_key = (api_key or "").strip() or settings.deepseek_api_key
        effective_url = (base_url or "").strip() or settings.deepseek_base_url
        effective_model = (model or "").strip() or settings.deepseek_model
        if not effective_key:
            return {
                "provider": provider,
                "configured": False,
                "status": "unconfigured",
                "checked_at": None,
                "message": "未提供 DeepSeek API Key，无法测试",
            }
    elif provider == "embedding":
        effective_key = (api_key or "").strip() or settings.embedding_api_key
        effective_url = (base_url or "").strip() or settings.embedding_base_url
        effective_model = (model or "").strip() or settings.embedding_model
        if not (effective_key and effective_url and effective_model):
            return {
                "provider": provider,
                "configured": False,
                "status": "unconfigured",
                "checked_at": None,
                "message": "Embedding 需要同时提供 地址 / Key / 模型 三项才能测试",
            }
        temp_settings = replace(
            settings,
            embedding_api_key=effective_key,
            embedding_base_url=effective_url,
            embedding_model=effective_model,
        )
    else:
        raise ValueError("Unknown provider")

    audit = None
    started = None
    if db is not None:
        audit, started = begin_call(
            db,
            provider=provider,
            operation="connectivity_test",
            model=effective_model,
            request_units=1,
        )
    try:
        if provider == "deepseek":
            # 用 GET /models 探活，避免 chat/completions 受模型空内容/reasoner 干扰
            probe_url = f"{effective_url.rstrip('/')}/models"
            response = httpx.get(
                probe_url,
                headers={"Authorization": f"Bearer {effective_key}"},
                timeout=min(settings.deepseek_timeout_seconds, 20.0),
            )
            response.raise_for_status()
        else:
            EmbeddingClient(temp_settings).embed(["连接测试"])
        status = "connected"
        message = "连接成功，配置可用"
    except Exception as exc:
        status = _error_status(exc)
        message = _error_message(provider, exc, effective_url)
        if audit is not None and started is not None:
            finish_call(
                db,
                audit,
                started,
                status=provider_status_from_error(exc),
                error_type=type(exc).__name__,
            )
    else:
        if audit is not None and started is not None:
            finish_call(db, audit, started, status="success", response_units=1)

    now = datetime.now(UTC)
    LAST_RESULTS[provider] = {"status": status, "checked_at": now}
    return {
        "provider": provider,
        "configured": True,
        "status": status,
        "checked_at": now.isoformat(),
        "message": message,
    }
