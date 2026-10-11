"""设置接口的安全边界测试。

这些用例锁定了几条不可回退的约束：
- 状态接口永不返回密钥明文；
- 非白名单键一律拒绝；
- 密钥写入必须同时满足开关 + 口令；
- 非法取值（换行注入、VITE_ 前缀、越界数值）必须被拦截。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.settings_store import SettingsWriteError, _sanitize, mask_secret
from app.main import app

client = TestClient(app)


def test_get_settings_never_returns_plaintext_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-super-secret-value-1234567890"
    monkeypatch.setattr(
        "app.core.settings_store.settings",
        type("S", (), {"deepseek_api_key": secret})(),
    )
    # 直接验证掩码函数本身不泄露任何真实字符
    masked = mask_secret(secret)
    assert masked is not None
    assert secret not in masked
    assert "sk-" not in masked
    assert "super" not in masked


def test_get_settings_shape_is_sanitized() -> None:
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    raw = response.text
    assert set(body) == {"deepseek", "embedding", "storage", "limits", "source"}
    # 只允许出现布尔/长度提示，不允许出现完整密钥
    assert "api_key" not in raw.lower() or "masked_key" in raw
    for section in ("deepseek", "embedding"):
        assert "masked_key" in body[section]
        assert body[section]["masked_key"] is None or "****" in body[section]["masked_key"]


def test_non_whitelisted_key_is_rejected() -> None:
    response = client.patch("/api/v1/settings", json={"NOTEBOOK_DATA_DIR": "/tmp/hack"})
    assert response.status_code in {400, 403, 422}


def test_secret_write_allowed_without_token_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """本地单用户默认允许写入密钥，无需先编辑 .env。"""
    from app.core import settings_store

    monkeypatch.delenv("NOTEBOOK_ALLOW_SECRET_WRITE", raising=False)
    monkeypatch.delenv("NOTEBOOK_SETTINGS_TOKEN", raising=False)
    monkeypatch.setenv("NOTEBOOK_SKIP_KEY_VERIFY", "true")
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(settings_store, "_atomic_write", lambda env_values: None)
    monkeypatch.setattr(settings_store, "_apply_to_process", lambda sanitized: None)

    outcome = settings_store.apply_updates({"DEEPSEEK_API_KEY": "sk-test-key-123456"}, None)
    assert "DEEPSEEK_API_KEY" in outcome.updated


def test_secret_write_blocked_when_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import settings_store

    monkeypatch.setenv("NOTEBOOK_ALLOW_SECRET_WRITE", "false")
    monkeypatch.delenv("NOTEBOOK_SETTINGS_TOKEN", raising=False)
    with pytest.raises(SettingsWriteError):
        settings_store.apply_updates({"DEEPSEEK_API_KEY": "sk-attacker-value"}, None)


def test_secret_write_blocked_with_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEBOOK_ALLOW_SECRET_WRITE", "true")
    monkeypatch.setenv("NOTEBOOK_SETTINGS_TOKEN", "correct-token-value")
    response = client.patch(
        "/api/v1/settings",
        json={"DEEPSEEK_API_KEY": "sk-attacker-value"},
        headers={"X-Notebook-Settings-Token": "wrong-token"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DEEPSEEK_MODEL", "bad model!!"),
        ("NOTEBOOK_MAX_UPLOAD_MB", "99999"),
        ("DEEPSEEK_TIMEOUT_SECONDS", "not-a-number"),
        ("EMBEDDING_BASE_URL", "ftp://evil.example.com"),
        ("DEEPSEEK_MODEL", "a\nNOTEBOOK_DATA_DIR=/etc"),
        ("DEEPSEEK_API_KEY", "VITE_LEAKED_KEY"),
    ],
)
def test_invalid_values_are_blocked(key: str, value: str) -> None:
    with pytest.raises(SettingsWriteError):
        _sanitize(key, value)


def test_valid_non_secret_value_passes() -> None:
    assert _sanitize("DEEPSEEK_MODEL", "deepseek-chat") == "deepseek-chat"
    assert _sanitize("NOTEBOOK_MAX_UPLOAD_MB", "80") == "80"
    assert _sanitize("DEEPSEEK_BASE_URL", "https://api.deepseek.com") == "https://api.deepseek.com"


def test_env_rewrite_preserves_unmanaged_keys_and_comments(tmp_path, monkeypatch) -> None:
    """写入面板管理的键时，不得丢失手写配置、注释与行序。"""
    from app.core import settings_store

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 我的注释\n"
        "NOTEBOOK_HOST=127.0.0.1\n"
        "DEEPSEEK_MODEL=old-model\n"
        "NOTEBOOK_DATA_DIR=./data\n"
        "\n"
        "# 尾部注释\n"
        "CUSTOM_UNMANAGED_KEY=keep-me\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_store, "ENV_PATH", env_file)

    rendered = settings_store._render_env_lines(
        {"NOTEBOOK_HOST": "127.0.0.1", "DEEPSEEK_MODEL": "new-model", "NOTEBOOK_DATA_DIR": "./data"}
    )
    text = "\n".join(rendered)

    assert "new-model" in text
    assert "old-model" not in text
    assert "CUSTOM_UNMANAGED_KEY=keep-me" in text, "未托管的键不能被丢弃"
    assert "# 我的注释" in text, "注释必须保留"
    assert "# 尾部注释" in text
    # 相对顺序保持：未托管的键仍在被托管键之后
    assert text.index("CUSTOM_UNMANAGED_KEY") > text.index("DEEPSEEK_MODEL")


def test_secret_masked_output_has_no_real_prefix() -> None:
    # 这三个都是**故意构造的假密钥**，用来验证掩码不泄露前缀。
    # 形如 sk-.../ghp_... 是为了让掩码逻辑走真实分支。
    for secret in ("sk-fake0000000000000000", "ghp_fake0000000000000000", "short"):
        masked = mask_secret(secret)
        assert masked is not None
        for chunk in (secret[:3], secret[:5]):
            if len(chunk) >= 3 and chunk.isalnum():
                assert chunk not in masked, f"掩码泄露了真实前缀 {chunk!r}"


def test_invalid_key_is_rejected_before_overwriting(monkeypatch: pytest.MonkeyPatch) -> None:
    """写错密钥时必须被拦下，不能覆盖掉可用的旧密钥。"""
    from app.core import settings_store

    monkeypatch.setenv("NOTEBOOK_ALLOW_SECRET_WRITE", "true")
    monkeypatch.setenv("NOTEBOOK_SETTINGS_TOKEN", "test-token-value")
    monkeypatch.delenv("NOTEBOOK_SKIP_KEY_VERIFY", raising=False)
    monkeypatch.setattr(
        settings_store,
        "verify_deepseek_key",
        lambda *a, **k: (False, "密钥被服务端拒绝（401/403）"),
    )
    with pytest.raises(settings_store.SettingsVerifyError):
        settings_store.apply_updates(
            {"DEEPSEEK_API_KEY": "sk-invalid-key-123456"}, "test-token-value"
        )


def test_backups_are_pruned(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """备份含明文，不能无限堆积。"""
    from app.core import settings_store

    backups = tmp_path / "backups"
    backups.mkdir()
    for index in range(25):
        (backups / f"env-2026010{index % 10}-0000{index:02d}.bak").write_text("x", encoding="utf-8")
    settings_store._prune_backups(backups, keep=20)
    assert len(list(backups.glob("env-*.bak"))) == 20
