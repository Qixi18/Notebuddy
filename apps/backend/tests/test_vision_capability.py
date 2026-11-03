from __future__ import annotations

import base64
import json


def test_vision_preflight_verifies_image_and_persists_only_non_secret_metadata(monkeypatch, tmp_path):
    from app.document_processing.engines import vision

    cache = tmp_path / "vision-capabilities.json"
    monkeypatch.setattr(vision, "_capability_secret_path", lambda: tmp_path / "vision-capability-hmac.key")
    monkeypatch.setattr(vision, "_capability_path", lambda: cache)
    captured = {}
    probe = vision._probe_image()
    monkeypatch.setattr(vision, "_probe_image", lambda: probe)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": probe[1]}}]}

    def post(url, *, json, headers, timeout):
        captured.update(url=url, payload=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("httpx.post", post)
    config = {
        "base_url": "https://vision.example/v1/", "api_key": "secret-not-to-persist",
        "model": "vision-model", "timeout_seconds": 23,
    }

    result = vision.preflight_image_support(config)

    assert result["status"] == "verified"
    assert result["supports_image_input"] is True
    assert captured["url"] == "https://vision.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-not-to-persist"
    assert captured["timeout"] == 23
    assert captured["payload"]["messages"][0]["content"][1]["type"] == "image_url"
    assert base64.b64encode(probe[0]).decode("ascii") in captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert probe[1] not in captured["payload"]["messages"][0]["content"][0]["text"].lower()
    stored = cache.read_text(encoding="utf-8")
    assert "secret-not-to-persist" not in stored
    assert "vision.example" not in stored
    assert vision.capability_status(config)["status"] == "verified"
    rotated = {**config, "api_key": "replacement-key-not-verified"}
    assert vision.capability_status(rotated)["status"] == "unverified"


def test_vision_preflight_rejects_unsupported_image_and_does_not_cache(monkeypatch, tmp_path):
    from app.document_processing.engines import vision

    cache = tmp_path / "vision-capabilities.json"
    monkeypatch.setattr(vision, "_capability_secret_path", lambda: tmp_path / "vision-capability-hmac.key")
    monkeypatch.setattr(vision, "_capability_path", lambda: cache)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "UNSUPPORTED_IMAGE"}}]}

    monkeypatch.setattr("httpx.post", lambda *_a, **_k: Response())
    config = {"base_url": "https://vision.example/v1", "model": "vision-model"}

    result = vision.preflight_image_support(config)

    assert result["status"] == "unsupported"
    assert result["supports_image_input"] is False
    assert not cache.exists()
    assert vision.capability_status(config)["supports_image_input"] is False


def test_vision_preflight_handles_provider_error_without_secret_leak(monkeypatch, tmp_path):
    import httpx

    from app.document_processing.engines import vision

    cache = tmp_path / "vision-capabilities.json"
    monkeypatch.setattr(vision, "_capability_secret_path", lambda: tmp_path / "vision-capability-hmac.key")
    monkeypatch.setattr(vision, "_capability_path", lambda: cache)

    def post(*_args, **_kwargs):
        request = httpx.Request("POST", "https://vision.example/v1/chat/completions")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr("httpx.post", post)
    result = vision.preflight_image_support({
        "base_url": "https://vision.example/v1", "model": "vision-model", "api_key": "secret-key-value",
    })

    assert result["status"] == "authentication_failed"
    assert "secret-key-value" not in result["message"]
    assert not cache.exists()


def test_vision_fingerprint_binds_credentials_without_persisting_them(monkeypatch, tmp_path):
    from app.document_processing.engines import vision

    monkeypatch.setattr(vision, "_capability_secret_path", lambda: tmp_path / "vision-capability-hmac.key")

    first = {"base_url": "https://vision.example/v1/", "model": "vision-model", "api_key": "one"}
    second = {"base_url": "https://vision.example/v1", "model": "vision-model", "api_key": "two"}
    assert vision.config_fingerprint(first) != vision.config_fingerprint(second)


def test_unsafe_environment_vision_url_is_not_reflected_or_snapshotted(monkeypatch):
    from app.core.settings_store import build_status
    from app.document_processing.routes import provider_snapshot

    monkeypatch.setenv("NOTEBOOK_VISION_BASE_URL", "https://user:password@vision.example/v1?token=private")
    status = build_status()
    snapshot = provider_snapshot()
    serialized = repr((status["vision"], snapshot))
    assert "password" not in serialized
    assert "private" not in serialized
    assert status["vision"]["base_url"] is None
    assert snapshot["vision"]["base_url"] == ""


def test_vision_client_uses_the_same_captured_credentials_that_passed_preflight(monkeypatch, tmp_path):
    from app.document_processing.engines import vision
    from app.document_processing.routes import vision_client

    monkeypatch.setattr(vision, "_capability_secret_path", lambda: tmp_path / "vision-capability-hmac.key")
    monkeypatch.setattr(vision, "_capability_path", lambda: tmp_path / "vision-capabilities.json")
    monkeypatch.setenv("NOTEBOOK_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("NOTEBOOK_VISION_MODEL", "vision-model")
    monkeypatch.setenv("NOTEBOOK_VISION_API_KEY", "credential-key-original")
    snapshot = vision.config_snapshot()
    effective = vision._settings(snapshot)
    fingerprint = vision.config_fingerprint(effective)
    (tmp_path / "vision-capabilities.json").write_text(json.dumps({fingerprint: {
        "supports_image_input": True, "checked_at": "test",
    }}), encoding="utf-8")

    vision.require_image_capability(effective)
    monkeypatch.setenv("NOTEBOOK_VISION_API_KEY", "credential-key-rotated")
    client = vision_client({"vision": snapshot}, effective)

    assert client.settings.deepseek_api_key == "credential-key-original"
    assert vision.config_fingerprint(vision._settings()) != fingerprint

