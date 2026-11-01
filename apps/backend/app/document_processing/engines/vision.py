"""Optional OpenAI-compatible vision engine for formulas, tables and diagrams.

Disabled by default.  Configure with environment variables::

    NOTEBOOK_VISION_BASE_URL=https://.../v1
    NOTEBOOK_VISION_API_KEY=...
    NOTEBOOK_VISION_MODEL=...
    NOTEBOOK_VISION_TIMEOUT_SECONDS=60

The engine never fabricates structure: when it is unavailable or uncertain the
adapter records ``needs_vision`` / ``uncertain`` instead of guessing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
import tempfile
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings as app_settings
from app.document_processing.engines.pdf_text import EngineInfo

logger = logging.getLogger(__name__)

PROMPT = (
    "你是教材局部图片结构化识别器。只输出 JSON，不要解释。schema："
    '{"description":"中文说明","latex":"公式LaTeX或null",'
    '"table":{"rows":[["单元格"]],"header_rows":1}或null,'
    '"figure":{"kind":"diagram|chart|circuit|photo|formula|table|other",'
    '"nodes":["关键节点"],"edges":["A -> B"]}或null,'
    '"uncertain":true/false}。'
    "仅依据图片中看得见的内容；看不清或无法确定时 uncertain=true，禁止编造。"
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class VisionResult:
    description: str | None = None
    latex: str | None = None
    table: dict[str, Any] | None = None
    figure: dict[str, Any] | None = None
    uncertain: bool = True
    model: str | None = None
    raw: str | None = None
    warnings: list[str] = field(default_factory=list)


class VisionCapabilityError(RuntimeError):
    """The configured visual model has not passed its image-input preflight."""


def _settings(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = overrides or {}
    raw_base_url = str(values.get("base_url", os.getenv("NOTEBOOK_VISION_BASE_URL") or "")).strip()
    try:
        parsed_url = urlsplit(raw_base_url)
    except ValueError:
        parsed_url = None
    valid_base_url = bool(parsed_url and
        parsed_url.scheme in {"http", "https"} and parsed_url.hostname
        and not parsed_url.username and not parsed_url.password
        and not parsed_url.query and not parsed_url.fragment
    )
    # Never reflect or persist URL userinfo/query/fragment from legacy .env values.
    base_url = raw_base_url.rstrip("/") if valid_base_url else ""
    api_key = str(values.get("api_key", os.getenv("NOTEBOOK_VISION_API_KEY") or "")).strip()
    model = str(values.get("model", os.getenv("NOTEBOOK_VISION_MODEL") or "")).strip()
    try:
        timeout = max(5.0, float(values.get("timeout_seconds", os.getenv("NOTEBOOK_VISION_TIMEOUT_SECONDS", "60"))))
    except ValueError:
        timeout = 60.0
    return {"base_url": base_url, "api_key": api_key, "model": model, "timeout": timeout}


def config_snapshot() -> dict[str, Any]:
    values = _settings()
    return {"base_url": values["base_url"], "model": values["model"],
            "timeout_seconds": values["timeout"]}


def config_fingerprint(config: dict[str, Any]) -> str:
    values = _settings(config)
    credential_fingerprint = hmac.new(
        _capability_secret(), values["api_key"].encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    identity = {"base_url": str(config.get("base_url") or "").rstrip("/"),
                "model": str(config.get("model") or ""),
                "credential_fingerprint": credential_fingerprint}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def _capability_path():
    return app_settings.data_dir / "vision-capabilities.json"


def _capability_secret_path():
    return app_settings.data_dir / "vision-capability-hmac.key"


def _capability_secret() -> bytes:
    """Create a local HMAC key so capability records never contain raw API keys."""
    path = _capability_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False,
                                             suffix=".tmp") as handle:
                temporary_path = handle.name
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                pass
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
    secret = path.read_bytes()
    if len(secret) != 32:
        raise RuntimeError("视觉能力凭据校验密钥无效")
    return secret


def _read_capabilities() -> dict[str, Any]:
    try:
        value = json.loads(_capability_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def capability_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    values = _settings(config) if config is not None else _settings()
    if not values["base_url"] or not values["model"]:
        return {"status": "unconfigured", "supports_image_input": False,
                "model": values["model"] or None, "checked_at": None}
    row = _read_capabilities().get(config_fingerprint(values))
    if not isinstance(row, dict) or row.get("supports_image_input") is not True:
        return {"status": "unverified", "supports_image_input": False,
                "model": values["model"], "checked_at": None}
    return {"status": "verified", "supports_image_input": True,
            "model": values["model"], "checked_at": row.get("checked_at")}


def require_image_capability(config: dict[str, Any] | None = None) -> None:
    state = capability_status(config)
    if not state["supports_image_input"]:
        raise VisionCapabilityError("视觉模型尚未通过图片输入预检；请先在设置中执行视觉模型预检")


def _probe_image() -> tuple[bytes, str]:
    colors = [("red", (255, 0, 0)), ("green", (0, 255, 0)),
              ("blue", (0, 0, 255)), ("yellow", (255, 255, 0))]
    left, right = secrets.SystemRandom().sample(colors, 2)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))

    scanline = b"\x00" + bytes(left[1] * 8 + right[1] * 8)
    raw = scanline * 8
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 8, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    return png, left[0]


def preflight_image_support(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one small explicit image request and cache only the non-secret result."""
    values = _settings(overrides)
    if not values["base_url"] or not values["model"]:
        return {"status": "unconfigured", "supports_image_input": False,
                "model": values["model"] or None, "message": "请配置视觉模型地址和模型 ID"}
    import httpx

    png, expected_left_color = _probe_image()
    payload = {
        "model": values["model"], "temperature": 0, "max_tokens": 32, "stream": False,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "这是图片输入能力预检。请只用一个英文颜色词回答图片左半边的颜色；如果无法读取图片，请回答 UNSUPPORTED_IMAGE。"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}},
        ]}],
    }
    headers = {"Content-Type": "application/json"}
    if values["api_key"]:
        headers["Authorization"] = f"Bearer {values['api_key']}"
    try:
        response = httpx.post(f"{values['base_url']}/chat/completions", json=payload,
                              headers=headers, timeout=values["timeout"])
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("invalid response body")
        choices = body.get("choices") or []
        message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
        content = message.get("content")
        normalized = content.strip().lower() if isinstance(content, str) else ""
        if (not re.search(rf"\b{re.escape(expected_left_color)}\b", normalized)
                or "unsupported_image" in normalized):
            return {"status": "unsupported", "supports_image_input": False,
                    "model": values["model"], "message": "模型未能确认读取图片，请检查视觉模型配置"}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        return {"status": "authentication_failed" if code in {401, 403} else "unavailable",
                "supports_image_input": False, "model": values["model"],
                "message": f"视觉模型预检失败：HTTP {code}"}
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return {"status": "unavailable", "supports_image_input": False,
                "model": values["model"], "message": "视觉模型预检失败：服务不可用或响应格式无效"}

    from datetime import UTC, datetime

    path = _capability_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = _read_capabilities()
    checked_at = datetime.now(UTC).isoformat()
    cached[config_fingerprint(values)] = {"supports_image_input": True, "checked_at": checked_at}
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         delete=False, suffix=".tmp") as handle:
            temporary_path = handle.name
            json.dump(cached, handle, ensure_ascii=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return {"status": "verified", "supports_image_input": True,
            "model": values["model"], "checked_at": checked_at,
            "message": "图片输入预检通过"}


def availability() -> EngineInfo:
    settings = _settings()
    if not settings["base_url"] or not settings["model"]:
        return EngineInfo(
            name="openai-compatible-vision", version="0", available=False,
            reason="未配置 NOTEBOOK_VISION_BASE_URL / NOTEBOOK_VISION_MODEL",
        )
    if not capability_status(settings)["supports_image_input"]:
        return EngineInfo(name="openai-compatible-vision", version="0", available=False,
                          reason="视觉模型尚未通过图片输入预检")
    return EngineInfo(
        name="openai-compatible-vision", version="1", available=True,
        capabilities=("figure_description", "formula_latex", "table_structure"),
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    match = _JSON_FENCE.search(text)
    candidate = match.group(1) if match else text.strip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start:end + 1])
        except (TypeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def describe(image: bytes, *, mime: str = "image/png") -> VisionResult:
    require_image_capability()
    info = availability()
    if not info.available:
        raise RuntimeError(info.reason or "视觉引擎不可用")
    settings = _settings()
    import httpx

    encoded = base64.b64encode(image).decode("ascii")
    payload = {
        "model": settings["model"],
        "temperature": 0,
        "max_tokens": 2000,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
        }],
    }
    from app.services.processing_budget import ProcessingBudgetError, active_budget_guard

    guard = active_budget_guard()
    reservation = None
    usage_settled = False
    if guard is not None:
        reservation = guard.before_request(provider="vision", model=settings["model"],
                                           messages=payload["messages"], max_tokens=2000)
    headers = {"Content-Type": "application/json"}
    if settings["api_key"]:
        headers["Authorization"] = f"Bearer {settings['api_key']}"
    try:
        with httpx.Client(timeout=settings["timeout"]) as client:
            response = client.post(
                f"{settings['base_url']}/chat/completions", json=payload, headers=headers,
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage")
        if guard is not None and reservation is not None:
            parsed_usage = {
                key: int(usage[key]) for key in ("prompt_tokens", "completion_tokens")
                if isinstance(usage, dict) and isinstance(usage.get(key), (int, float))
            } or None
            guard.after_response(reservation, parsed_usage)
            usage_settled = True
        content = ""
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")
    except ProcessingBudgetError:
        raise
    except Exception as exc:
        if guard is not None and reservation is not None and not usage_settled:
            guard.request_failed(reservation, exc)
        # Never include the request (or its Authorization header) in the error.
        return VisionResult(uncertain=True, model=settings["model"],
                            warnings=[f"视觉识别失败：{type(exc).__name__}"])
    parsed = _extract_json(content)
    if parsed is None:
        return VisionResult(uncertain=True, model=settings["model"], raw=content[:2000],
                            warnings=["视觉模型未返回可解析的 JSON"])
    table = parsed.get("table") if isinstance(parsed.get("table"), dict) else None
    figure = parsed.get("figure") if isinstance(parsed.get("figure"), dict) else None
    return VisionResult(
        description=str(parsed.get("description") or "").strip() or None,
        latex=str(parsed.get("latex") or "").strip() or None,
        table=table,
        figure=figure,
        uncertain=bool(parsed.get("uncertain", False)),
        model=settings["model"],
        raw=content[:4000],
    )
