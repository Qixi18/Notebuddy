from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderSettings(SettingsSection):
    configured: bool
    masked_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout_seconds: float | None = None
    image_capability: dict | None = None


class StorageSettings(SettingsSection):
    data_dir: str
    database: str
    max_upload_mb: int
    processing_route: Literal["standard", "llm"] = "standard"


class SettingsLimits(SettingsSection):
    allowed_extensions: list[str]
    editable_keys: list[str]
    secret_write_enabled: bool
    token_required: bool


class SettingsSource(SettingsSection):
    env_path: str
    env_exists: bool
    override_keys: list[str]


class SettingsStatus(SettingsSection):
    deepseek: ProviderSettings
    embedding: ProviderSettings
    vision: ProviderSettings
    budget: dict
    storage: StorageSettings
    limits: SettingsLimits
    source: SettingsSource


class SettingsUpdate(SettingsSection):
    NOTEBOOK_DOCUMENT_PROCESSING_ROUTE: str | None = None
    DEEPSEEK_BASE_URL: str | None = None
    DEEPSEEK_MODEL: str | None = None
    DEEPSEEK_TIMEOUT_SECONDS: str | None = None
    NOTEBOOK_MAX_UPLOAD_MB: str | None = None
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_MODEL: str | None = None
    NOTEBOOK_VISION_BASE_URL: str | None = None
    NOTEBOOK_VISION_MODEL: str | None = None
    NOTEBOOK_VISION_TIMEOUT_SECONDS: str | None = None
    DEEPSEEK_INPUT_COST_PER_MILLION: str | None = None
    DEEPSEEK_OUTPUT_COST_PER_MILLION: str | None = None
    DEEPSEEK_PRICE_VERSION: str | None = None
    DEEPSEEK_PRICE_SOURCE: str | None = None
    NOTEBOOK_VISION_INPUT_COST_PER_MILLION: str | None = None
    NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION: str | None = None
    NOTEBOOK_VISION_MAX_IMAGE_TOKENS: str | None = None
    NOTEBOOK_VISION_PRICE_VERSION: str | None = None
    NOTEBOOK_VISION_PRICE_SOURCE: str | None = None
    NOTEBOOK_BUDGET_USD_CNY_RATE: str | None = None
    NOTEBOOK_BUDGET_FX_RATE_SOURCE: str | None = None
    NOTEBOOK_BUDGET_FX_RATE_AS_OF: str | None = None
    NOTEBOOK_BUDGET_FX_BUFFER_PERCENT: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    EMBEDDING_API_KEY: str | None = None
    NOTEBOOK_VISION_API_KEY: str | None = None


class SettingsUpdateResponse(SettingsSection):
    updated: list[str]
    backup_path: str | None = None
    status: SettingsStatus
    warnings: list[str] = Field(default_factory=list)


class ProviderConnectivityTestRequest(SettingsSection):
    """单项连通性测试：使用面板草稿值（不落盘），各 API 相互独立。"""

    provider: Literal["deepseek", "embedding"]
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class VisionCapabilityTestRequest(SettingsSection):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = Field(default=60, ge=5, le=600)
