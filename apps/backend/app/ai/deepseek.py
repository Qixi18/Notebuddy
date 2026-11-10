from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.core.config import Settings, settings


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def _json_failure_details(error: json.JSONDecodeError, finish_reason: str | None) -> str:
    # Keep diagnostics useful without exposing model text or arbitrary provider
    # fields. Never include error.doc, a content excerpt, or a raw provider value.
    kinds = {
        "Invalid \\escape": "invalid_escape",
        "Invalid control character at": "invalid_control_character",
        "Unterminated string starting at": "unterminated_string",
        "Expecting ',' delimiter": "expected_comma",
        "Expecting ':' delimiter": "expected_colon",
        "Expecting property name enclosed in double quotes": "expected_property_name",
        "Expecting value": "expected_value",
        "Extra data": "extra_data",
    }
    kind = kinds.get(error.msg, "invalid_syntax")
    known_reasons = {"stop", "length", "content_filter", "tool_calls",
                     "insufficient_system_resource", "aborted"}
    reason = finish_reason if finish_reason in known_reasons else "unknown"
    return (
        f"json_error={kind}; line={error.lineno}, column={error.colno}; "
        f"offset={error.pos}, chars={len(error.doc)}; finish_reason={reason}"
    )


class DeepSeekError(RuntimeError):
    """Raised when the configured DeepSeek provider cannot return a result."""

    def __init__(
        self, message: str, *, status_code: int | None = None, code: str = "provider_error",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


class DeepSeekClient:
    def __init__(self, provider_settings: Settings = settings) -> None:
        self.settings = provider_settings
        self.last_usage: dict[str, int] | None = None
        self.last_finish_reason: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        max_tokens: int = 3000,
        temperature: float = 0.2,
        thinking: bool | None = None,
    ) -> str:
        from app.ai.request_control import check_request_allowed
        check_request_allowed()
        if not self.configured:
            raise DeepSeekError("DEEPSEEK_API_KEY 未配置")
        from app.services.processing_budget import ProcessingBudgetError, active_budget_guard

        guard = active_budget_guard()
        reservation = None
        if guard is not None:
            try:
                reservation = guard.before_request(
                    provider="deepseek", model=self.settings.deepseek_model,
                    messages=messages, max_tokens=max_tokens,
                )
            except ProcessingBudgetError as exc:
                raise DeepSeekError(str(exc), code=exc.code) from exc
        self.last_finish_reason = None

        payload: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if thinking is not None:
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}

        try:
            response = httpx.post(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.deepseek_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            choices = body.get("choices") or []
            finish_reason = choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else None
            self.last_finish_reason = finish_reason if isinstance(finish_reason, str) else None
            usage = body.get("usage")
            self.last_usage = {
                key: int(usage[key])
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage, dict) and isinstance(usage.get(key), (int, float))
            } or None
            if guard is not None and reservation is not None:
                try:
                    guard.after_response(reservation, self.last_usage)
                except ProcessingBudgetError as exc:
                    raise DeepSeekError(str(exc), code=exc.code) from exc
            content = body["choices"][0]["message"]["content"]
            if self.last_finish_reason == "length" and json_mode:
                # A thinking model may exhaust the budget before emitting any
                # content. Even parseable JSON cannot prove the answer is whole.
                raise DeepSeekError(
                    "DeepSeek JSON 输出达到输出长度限制，结果可能被截断",
                    code="output_truncated",
                )
            if not isinstance(content, str) or not content.strip():
                if self.last_finish_reason == 'length':
                    raise DeepSeekError('模型输出被截断，请减小批次后重试', code='output_truncated')
                raise DeepSeekError("DeepSeek 返回了空内容", code='provider_empty')
            return content.strip()
        except httpx.HTTPStatusError as exc:
            if guard is not None and reservation is not None:
                guard.request_failed(reservation, exc)
            self.last_usage = None
            self.last_finish_reason = None
            raise DeepSeekError(
                f"DeepSeek 调用失败：HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                retry_after=_retry_after(exc.response.headers.get('Retry-After')),
            ) from exc
        except DeepSeekError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            if guard is not None and reservation is not None:
                guard.request_failed(reservation, exc)
            self.last_usage = None
            self.last_finish_reason = None
            raise DeepSeekError(f"DeepSeek 调用失败：{type(exc).__name__}",
                                code='provider_transport' if isinstance(exc, httpx.HTTPError) else 'provider_response_invalid') from exc

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 3000,
        thinking: bool | None = None,
    ) -> dict[str, Any]:
        content = self.complete(
            messages, json_mode=True, max_tokens=max_tokens, thinking=thinking,
        )
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            details = _json_failure_details(exc, self.last_finish_reason)
            raise DeepSeekError(
                f"DeepSeek 返回内容不是有效 JSON（{details}）", code="invalid_json",
            ) from exc
        if not isinstance(decoded, dict):
            raise DeepSeekError("DeepSeek JSON 输出不是对象", code="invalid_json")
        return decoded

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 3000,
        temperature: float = 0.2,
    ) -> Iterator[dict[str, Any]]:
        """流式 chat completions，支持 function calling（agent 循环专用）。

        逐块产出事件：
        - ``{"type": "reasoning", "text": str}`` 思考模式思维链增量（仅思考模型输出）；
        - ``{"type": "delta", "text": str}`` 回答文本增量；
        - ``{"type": "tool_calls", "tool_calls": [...], "reasoning_content": str}``
          流结束后聚合完成的工具调用，每项为 ``{"id", "name", "arguments"}``
          （arguments 为原始 JSON 字符串）；``reasoning_content`` 是本轮思维链全文，
          思考模型要求在下一轮回传，否则请求报 400；
        - 最后一条之后 ``last_usage`` 与 ``complete()`` 语义一致。

        生成器是惰性的：调用方必须完整迭代才会触发请求并遇到异常。
        """
        if not self.configured:
            raise DeepSeekError("DEEPSEEK_API_KEY 未配置")

        payload: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # 工具调用按 index 分槽聚合：id/name 与 arguments 分片可能落在不同 chunk
        pending: dict[int, dict[str, str]] = {}
        reasoning_parts: list[str] = []
        usage: dict[str, int] | None = None
        try:
            with httpx.stream(
                "POST",
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.deepseek_timeout_seconds,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = {
                            key: int(chunk["usage"][key])
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                            if isinstance(chunk["usage"].get(key), (int, float))
                        } or None
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        reasoning_parts.append(reasoning)
                        yield {"type": "reasoning", "text": reasoning}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield {"type": "delta", "text": content}
                    for call in delta.get("tool_calls") or []:
                        index = int(call.get("index") or 0)
                        slot = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if call.get("id"):
                            slot["id"] = str(call["id"])
                        function = call.get("function") or {}
                        if function.get("name"):
                            slot["name"] = str(function["name"])
                        arguments = function.get("arguments")
                        if isinstance(arguments, str):
                            slot["arguments"] += arguments
        except httpx.HTTPStatusError as exc:
            self.last_usage = None
            raise DeepSeekError(
                f"DeepSeek 调用失败：HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_usage = None
            raise DeepSeekError(f"DeepSeek 调用失败：{type(exc).__name__}") from exc

        self.last_usage = usage
        if pending:
            yield {
                "type": "tool_calls",
                "reasoning_content": "".join(reasoning_parts) or None,
                "tool_calls": [
                    {
                        "id": slot["id"] or f"call_{index}",
                        "name": slot["name"],
                        "arguments": slot["arguments"],
                    }
                    for index, slot in sorted(pending.items())
                ],
            }
