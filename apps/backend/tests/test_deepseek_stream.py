"""DeepSeekClient.chat_stream 的流式与工具调用聚合测试。

不访问真实服务：monkeypatch ``httpx.stream``，用伪造的 SSE 行序列验证
事件产出、分片聚合、用量记录与错误映射。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import httpx
import pytest

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.core.config import Settings


def _test_settings(api_key: str | None = "test-key") -> Settings:
    return Settings(
        data_dir=Path("."),
        max_upload_bytes=1,
        max_pages=1,
        deepseek_api_key=api_key,
        deepseek_base_url="http://deepseek.test",
        deepseek_model="deepseek-test",
        deepseek_timeout_seconds=1,
        deepseek_input_cost_per_million=0,
        deepseek_output_cost_per_million=0,
        tavily_api_key=None,
        web_search_timeout_seconds=1,
        embedding_base_url=None,
        embedding_api_key=None,
        embedding_model=None,
    )


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self) -> object:
        return iter(self._lines)


def _patch_httpx_stream(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    def fake_stream(method: str, url: str, **kwargs: object):
        return contextlib.nullcontext(_FakeStreamResponse(lines))

    monkeypatch.setattr(httpx, "stream", fake_stream)


def test_chat_stream_yields_text_deltas_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"delta":{"content":"，同学"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":4,"total_tokens":16}}',
        "data: [DONE]",
    ])
    client = DeepSeekClient(_test_settings())

    events = list(client.chat_stream([{"role": "user", "content": "问题"}]))

    assert events == [
        {"type": "delta", "text": "你好"},
        {"type": "delta", "text": "，同学"},
    ]
    assert client.last_usage == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}


def test_chat_stream_aggregates_fragmented_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """arguments 分片落在两个 chunk、id 只在首片出现时，聚合结果必须完整。"""
    _patch_httpx_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_7","function":{"name":"search_course","arguments":"{\\"query\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"导数\\"}"}}]}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ])
    client = DeepSeekClient(_test_settings())

    events = list(client.chat_stream([{"role": "user", "content": "问题"}], tools=[{"type": "function", "function": {"name": "search_course"}}]))

    assert events == [{
        "type": "tool_calls",
        "reasoning_content": None,
        "tool_calls": [{"id": "call_7", "name": "search_course", "arguments": '{"query":"导数"}'}],
    }]


def test_chat_stream_passes_back_reasoning_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """思考模型的思维链：先作为 reasoning 增量产出，工具调用事件里带回全文供回填。"""
    _patch_httpx_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"reasoning_content":"用户想查课件，"}}]}',
        'data: {"choices":[{"delta":{"reasoning_content":"先调用检索。"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"search_course","arguments":"{}"}}]}}]}',
        "data: [DONE]",
    ])
    client = DeepSeekClient(_test_settings())

    events = list(client.chat_stream([{"role": "user", "content": "问题"}], tools=[{"type": "function", "function": {"name": "search_course"}}]))

    assert events == [
        {"type": "reasoning", "text": "用户想查课件，"},
        {"type": "reasoning", "text": "先调用检索。"},
        {
            "type": "tool_calls",
            "reasoning_content": "用户想查课件，先调用检索。",
            "tool_calls": [{"id": "call_1", "name": "search_course", "arguments": "{}"}],
        },
    ]


def test_chat_stream_requires_api_key() -> None:
    client = DeepSeekClient(_test_settings(api_key=None))

    with pytest.raises(DeepSeekError, match="DEEPSEEK_API_KEY"):
        list(client.chat_stream([{"role": "user", "content": "问题"}]))


def test_chat_stream_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_stream(method: str, url: str, **kwargs: object):
        request = httpx.Request(method, url)

        def raise_status() -> None:
            raise httpx.HTTPStatusError("server error", request=request, response=httpx.Response(500, request=request))

        class _Response:
            def raise_for_status(self) -> None:
                raise_status()

            def iter_lines(self) -> object:
                return iter(())

        return contextlib.nullcontext(_Response())

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = DeepSeekClient(_test_settings())

    with pytest.raises(DeepSeekError, match="HTTP 500"):
        list(client.chat_stream([{"role": "user", "content": "问题"}]))
    assert client.last_usage is None


@pytest.mark.parametrize(
    ("finish_reason", "message"),
    [("length", "输出长度限制"), ("stop", "不是有效 JSON")],
)
def test_complete_json_marks_invalid_output_and_truncation(
    monkeypatch: pytest.MonkeyPatch, finish_reason: str, message: str,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"finish_reason": finish_reason,
                             "message": {"content": '{"nodes": ['}}],
            }

    def fake_post(*_args: object, **_kwargs: object) -> Response:
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = DeepSeekClient(_test_settings())

    with pytest.raises(DeepSeekError, match=message) as captured:
        client.complete_json([{"role": "user", "content": "生成"}])

    assert captured.value.code == ("output_truncated" if finish_reason == "length" else "invalid_json")
