"""单项连通性测试（面板草稿直测、各 API 独立）的单元用例。"""

from __future__ import annotations

import httpx
import pytest

from app.core import service_checks


class _FakeEmbedding:
    def __init__(self, provider_settings):
        self.settings = provider_settings

    def embed(self, texts):
        if (self.settings.embedding_api_key or "").startswith("bad"):
            raise RuntimeError("boom")
        return [[0.1, 0.2]]


@pytest.fixture(autouse=True)
def _patch_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks, "EmbeddingClient", _FakeEmbedding)


def _fake_get(*, status: int = 200, exc: Exception | None = None):
    def fake_get(url, headers=None, timeout=None):
        if exc is not None:
            raise exc
        return httpx.Response(status, request=httpx.Request("GET", url))

    return fake_get


def test_deepseek_without_key_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.settings, "deepseek_api_key", None)
    result = service_checks.test_connectivity("deepseek")
    assert result["status"] == "unconfigured"
    assert result["configured"] is False
    assert "未提供" in result["message"]


def test_embedding_requires_three_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.settings, "embedding_api_key", None)
    monkeypatch.setattr(service_checks.settings, "embedding_base_url", None)
    monkeypatch.setattr(service_checks.settings, "embedding_model", None)
    result = service_checks.test_connectivity(
        "embedding", api_key="sk-embed-key-123", base_url="https://emb.example.com"
    )
    assert result["status"] == "unconfigured"
    assert "三项" in result["message"]


def test_deepseek_connectivity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.settings, "deepseek_api_key", None)
    monkeypatch.setattr(service_checks.httpx, "get", _fake_get(status=200))
    result = service_checks.test_connectivity("deepseek", api_key="sk-good-key-1234567890")
    assert result["status"] == "connected"
    assert result["configured"] is True
    assert "成功" in result["message"]


def test_deepseek_bad_key_is_authentication_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.settings, "deepseek_api_key", None)
    monkeypatch.setattr(service_checks.httpx, "get", _fake_get(status=401))
    result = service_checks.test_connectivity("deepseek", api_key="sk-bad-key-1234567890")
    assert result["status"] == "authentication_failed"
    assert "拒绝" in result["message"]


def test_deepseek_timeout_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.httpx, "get", _fake_get(exc=httpx.ConnectTimeout("timeout")))
    result = service_checks.test_connectivity("deepseek", api_key="sk-timeout-key-123456")
    assert result["status"] == "timeout"


def test_embedding_uses_draft_values_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_checks.settings, "embedding_api_key", None)
    monkeypatch.setattr(service_checks.settings, "embedding_base_url", None)
    monkeypatch.setattr(service_checks.settings, "embedding_model", None)
    result = service_checks.test_connectivity(
        "embedding",
        api_key="sk-embed-key-1234567890",
        base_url="https://emb.example.com",
        model="text-embedding-3-small",
    )
    assert result["status"] == "connected"