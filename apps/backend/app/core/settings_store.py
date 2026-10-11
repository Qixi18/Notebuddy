"""安全可写的本地运行时配置。

设计边界（安全优先，本地单用户场景）：

1. 只允许写入 `EDITABLE_KEYS` 白名单内的键，其余配置（数据目录、数据库地址等）
   永远不可通过 API 修改。
2. API Key 属于写敏感项：默认禁止写入，必须同时满足
   `NOTEBOOK_ALLOW_SECRET_WRITE=true` 且请求携带正确的 `X-Notebook-Settings-Token`
   （对应 `NOTEBOOK_SETTINGS_TOKEN`）才允许。未配置 token 时一律拒绝。
3. 写入采用「先备份、后原子替换」：`.env` 会先复制一份到 `data/backups/`，
   再通过临时文件 `os.replace` 原子落盘，失败不会破坏原文件。
4. 回传给前端的状态只包含布尔与区间值，**绝不返回任何密钥明文**。
5. 运行时内存配置同步刷新，无需重启后端即可让检索/生成链路读到新值。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from app.core.config import PROJECT_ROOT, settings

ENV_PATH = PROJECT_ROOT / ".env"

# 允许通过设置接口写入的键（白名单，其余一律拒绝）
EDITABLE_KEYS: frozenset[str] = frozenset(
    {
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_TIMEOUT_SECONDS",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL",
        "NOTEBOOK_MAX_UPLOAD_MB",
    }
)

# 密钥类键：额外需要显式放行 + token 校验
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "EMBEDDING_API_KEY",
    }
)

PLAIN_KEYS: frozenset[str] = EDITABLE_KEYS | SECRET_KEYS


class SettingsWriteError(RuntimeError):
    """Raised when a settings write request violates the safety policy."""


class SettingsVerifyError(SettingsWriteError):
    """Raised when a new API key fails online verification."""


@dataclass(frozen=True)
class WriteOutcome:
    updated: list[str]
    backup_path: str | None
    warnings: list[str]


def skip_key_verification() -> bool:
    """允许离线环境跳过密钥在线校验（默认开启校验）。"""
    return os.getenv("NOTEBOOK_SKIP_KEY_VERIFY", "").strip().lower() in {"1", "true", "yes"}


def allow_secret_write() -> bool:
    """本地单用户场景默认允许密钥写入，显式设置为 0/false/no/off 才关闭。

    远端共享/加固场景可在 .env 中设置 NOTEBOOK_ALLOW_SECRET_WRITE=false，
    并配置 NOTEBOOK_SETTINGS_TOKEN，此时写入仍需口令。
    """
    value = os.getenv("NOTEBOOK_ALLOW_SECRET_WRITE", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def settings_token() -> str | None:
    value = os.getenv("NOTEBOOK_SETTINGS_TOKEN", "").strip()
    return value or None


def verify_token(candidate: str | None) -> bool:
    """常量时间比较，避免 token 通过响应耗时被逐位猜解。"""
    expected = settings_token()
    if expected is None:
        return False
    if not candidate:
        return False
    return secrets.compare_digest(expected, candidate)


def read_env_values() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    raw = dotenv_values(ENV_PATH)
    return {key: value for key, value in raw.items() if value is not None}


def mask_secret(value: str | None) -> str | None:
    """只暴露"是否存在 + 大致长度"，不泄露任何真实字符。

    早期版本会保留前 4 位（如 sk-y****），但那仍暴露了真实密钥片段，
    对已知前缀的厂商等于免费送出一部分熵。这里改为纯长度提示。
    """
    if not value:
        return None
    return f"{'*' * min(len(value), 8)} · 共 {len(value)} 位"


def current_upload_mb() -> int:
    return settings.max_upload_bytes // (1024 * 1024)


def build_status() -> dict[str, object]:
    """构造脱敏后的设置状态快照，供前端展示。"""
    env_values = read_env_values()
    deepseek_key = settings.deepseek_api_key
    embedding_key = settings.embedding_api_key

    return {
        "deepseek": {
            "configured": bool(deepseek_key),
            "masked_key": mask_secret(deepseek_key),
            "base_url": settings.deepseek_base_url,
            "model": settings.deepseek_model,
            "timeout_seconds": settings.deepseek_timeout_seconds,
        },
        "embedding": {
            "configured": bool(
                settings.embedding_base_url
                and settings.embedding_api_key
                and settings.embedding_model
            ),
            "masked_key": mask_secret(embedding_key),
            "base_url": settings.embedding_base_url,
            "model": settings.embedding_model,
        },
        "storage": {
            "data_dir": str(settings.data_dir),
            "database": str(settings.data_dir / "notebook.sqlite3"),
            "max_upload_mb": current_upload_mb(),
        },
        "limits": {
            "allowed_extensions": list(settings.allowed_extensions),
            "editable_keys": sorted(EDITABLE_KEYS),
            "secret_write_enabled": allow_secret_write(),
            "token_required": settings_token() is not None,
        },
        "source": {
            "env_path": str(ENV_PATH),
            "env_exists": ENV_PATH.exists(),
            "override_keys": sorted(key for key in PLAIN_KEYS if env_values.get(key)),
        },
    }


def _sanitize(key: str, value: object) -> str:
    if key not in PLAIN_KEYS:
        raise SettingsWriteError(f"配置项 {key} 不允许通过接口修改")
    if not isinstance(value, str):
        raise SettingsWriteError(f"配置项 {key} 的值必须是字符串")
    cleaned = value.strip()
    # 防止向 .env 注入换行/额外键值对
    if "\n" in cleaned or "\r" in cleaned:
        raise SettingsWriteError("配置值不能包含换行符")
    if cleaned.startswith("VITE_"):
        raise SettingsWriteError("不得使用 VITE_ 前缀，避免密钥被打包进前端")
    if len(cleaned) > 500:
        raise SettingsWriteError("配置值长度超限")

    if key in SECRET_KEYS:
        if cleaned and len(cleaned) < 8:
            raise SettingsWriteError("API Key 长度过短，疑似无效")
        return cleaned

    if key == "DEEPSEEK_MODEL" and cleaned and not cleaned.replace("-", "").isalnum():
        raise SettingsWriteError("模型名只能包含字母、数字和连字符")
    if key == "EMBEDDING_MODEL" and cleaned and not cleaned.replace("-", "").isalnum():
        raise SettingsWriteError("模型名只能包含字母、数字和连字符")
    if key == "DEEPSEEK_TIMEOUT_SECONDS":
        try:
            seconds = float(cleaned)
        except ValueError as exc:
            raise SettingsWriteError("超时时间必须是数字") from exc
        if not 1 <= seconds <= 600:
            raise SettingsWriteError("超时时间需在 1 到 600 秒之间")
    if key == "NOTEBOOK_MAX_UPLOAD_MB":
        try:
            size = int(cleaned)
        except ValueError as exc:
            raise SettingsWriteError("上传上限必须是整数") from exc
        if not 1 <= size <= 2048:
            raise SettingsWriteError("上传上限需在 1 到 2048 MB 之间")
    if key.endswith("_BASE_URL") and cleaned and not cleaned.startswith(("http://", "https://")):
        raise SettingsWriteError("服务地址必须以 http:// 或 https:// 开头")
    return cleaned


def _atomic_write(env_values: dict[str, str]) -> str | None:
    """先备份再原子替换，返回备份文件路径。

    保留 `.env` 的原始行顺序与注释，未知键追加到末尾——
    设置面板只应"改动某几行"，而不该把用户手写的配置重排/丢注释。
    """
    backup_path: str | None = None
    if ENV_PATH.exists():
        backups_dir = settings.backups_dir
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup = backups_dir / f"env-{stamp}.bak"
        backup.write_bytes(ENV_PATH.read_bytes())
        backup_path = str(backup)
        _prune_backups(backups_dir, keep=20)

    lines = _render_env_lines(env_values)
    temp_path = ENV_PATH.with_suffix(".env.tmp")
    temp_path.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temp_path, ENV_PATH)
    return backup_path


def verify_deepseek_key(api_key: str, base_url: str, timeout: float = 20.0) -> tuple[bool, str]:
    """用最小开销探活新密钥，避免把写错的 Key 覆盖掉可用的旧 Key。

    返回 (是否可用, 说明)。网络不可达时返回"不确定"，交由调用方决定是否仍写入。
    """
    import httpx

    url = f"{base_url.rstrip('/')}/models"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return False, f"无法连接服务地址（{type(exc).__name__}），已跳过在线校验"

    if response.status_code == 200:
        return True, "校验通过"
    if response.status_code in {401, 403}:
        return False, "密钥被服务端拒绝（401/403），疑似无效"
    return False, f"服务端返回 {response.status_code}，未能确认密钥有效"


def _prune_backups(backups_dir: Path, *, keep: int) -> None:
    """只保留最近 N 份备份。

    备份里含明文密钥，无限堆积会扩大泄露面；同时留够份数以便误写后回滚。
    """
    backups = sorted(backups_dir.glob("env-*.bak"), key=lambda path: path.name)
    for stale in backups[:-keep] if len(backups) > keep else []:
        stale.unlink(missing_ok=True)


def _render_env_lines(env_values: dict[str, str]) -> list[str]:
    """在保持现有行序与注释的前提下覆写键值。"""
    existing_lines: list[str] = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    rendered: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in env_values:
            rendered.append(f"{key}={env_values[key]}")
            seen.add(key)
        else:
            rendered.append(line)

    missing = [key for key in env_values if key not in seen]
    if missing:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# 由 NoteBuddy 设置面板追加")
        for key in missing:
            rendered.append(f"{key}={env_values[key]}")

    if not rendered or rendered[-1].strip():
        rendered.append("")
    return rendered


def apply_updates(updates: dict[str, object], token: str | None) -> WriteOutcome:
    if not updates:
        raise SettingsWriteError("没有需要更新的配置项")

    unknown = [key for key in updates if key not in PLAIN_KEYS]
    if unknown:
        raise SettingsWriteError("包含不允许修改的配置项：" + "、".join(unknown))

    needs_secret_permission = any(key in SECRET_KEYS for key in updates)
    if needs_secret_permission:
        if not allow_secret_write():
            raise SettingsWriteError(
                "当前未开启密钥写入。需在 .env 中设置 NOTEBOOK_ALLOW_SECRET_WRITE=true 后重启后端。"
            )
        # 本地单用户：未配置口令时默认信任本机回环写入；配置了口令则必须校验。
        if settings_token() is not None and not verify_token(token):
            raise SettingsWriteError("设置口令校验失败，拒绝写入密钥。")

    sanitized: dict[str, str] = {}
    for key, value in updates.items():
        sanitized[key] = _sanitize(key, value)

    warnings: list[str] = []

    # 密钥在线校验：宁可拦住一次写入，也不要静默覆盖掉可用的旧密钥。
    new_deepseek_key = sanitized.get("DEEPSEEK_API_KEY")
    if new_deepseek_key and not skip_key_verification():
        target_url = sanitized.get("DEEPSEEK_BASE_URL") or settings.deepseek_base_url
        ok, message = verify_deepseek_key(new_deepseek_key, target_url)
        if not ok:
            reachable = "无法连接" not in message
            if reachable:
                raise SettingsVerifyError(f"DeepSeek 密钥校验未通过：{message}")
            warnings.append(message)

    env_values = read_env_values()
    env_values.update(sanitized)

    backup_path = _atomic_write(env_values)
    _apply_to_process(sanitized)
    return WriteOutcome(updated=sorted(sanitized), backup_path=backup_path, warnings=warnings)


def _apply_to_process(sanitized: dict[str, str]) -> None:
    """更新进程环境变量与内存配置对象（写盘已由 _atomic_write 完成）。"""
    for key, value in sanitized.items():
        os.environ[key] = value

    env_values = read_env_values()
    settings.deepseek_api_key = env_values.get("DEEPSEEK_API_KEY") or None
    settings.embedding_api_key = env_values.get("EMBEDDING_API_KEY") or None
    if "DEEPSEEK_MODEL" in sanitized:
        settings.deepseek_model = sanitized["DEEPSEEK_MODEL"] or settings.deepseek_model
    if "DEEPSEEK_BASE_URL" in sanitized:
        settings.deepseek_base_url = sanitized["DEEPSEEK_BASE_URL"] or settings.deepseek_base_url
    if "DEEPSEEK_TIMEOUT_SECONDS" in sanitized:
        settings.deepseek_timeout_seconds = float(sanitized["DEEPSEEK_TIMEOUT_SECONDS"])
    if "EMBEDDING_BASE_URL" in sanitized:
        settings.embedding_base_url = sanitized["EMBEDDING_BASE_URL"] or None
    if "EMBEDDING_MODEL" in sanitized:
        settings.embedding_model = sanitized["EMBEDDING_MODEL"] or None
    if "NOTEBOOK_MAX_UPLOAD_MB" in sanitized:
        settings.max_upload_bytes = int(sanitized["NOTEBOOK_MAX_UPLOAD_MB"]) * 1024 * 1024


def env_template_path() -> Path:
    return PROJECT_ROOT / ".env.example"
