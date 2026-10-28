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
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

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


def _settings() -> dict[str, Any]:
    base_url = (os.getenv("NOTEBOOK_VISION_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("NOTEBOOK_VISION_API_KEY") or "").strip()
    model = (os.getenv("NOTEBOOK_VISION_MODEL") or "").strip()
    try:
        timeout = max(5.0, float(os.getenv("NOTEBOOK_VISION_TIMEOUT_SECONDS", "60")))
    except ValueError:
        timeout = 60.0
    return {"base_url": base_url, "api_key": api_key, "model": model, "timeout": timeout}


def availability() -> EngineInfo:
    settings = _settings()
    if not settings["base_url"] or not settings["model"]:
        return EngineInfo(
            name="openai-compatible-vision", version="0", available=False,
            reason="未配置 NOTEBOOK_VISION_BASE_URL / NOTEBOOK_VISION_MODEL",
        )
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
        content = ""
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")
    except Exception as exc:
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
