from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _resolve_data_dir() -> Path:
    configured = os.getenv("NOTEBOOK_DATA_DIR", "./data")
    configured_path = Path(configured)
    if not configured_path.is_absolute():
        configured_path = PROJECT_ROOT / configured_path
    return configured_path.resolve()


@dataclass
class Settings:
    """运行时可写的配置对象。

    注意：`data_dir` 与 `allowed_extensions` 视为结构约束，不通过设置接口修改；
    其余字段可由 `app.core.settings_store` 在写入 .env 后热更新，无需重启进程。
    """

    data_dir: Path
    max_upload_bytes: int
    max_pages: int
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    deepseek_input_cost_per_million: float
    deepseek_output_cost_per_million: float
    tavily_api_key: str | None
    web_search_timeout_seconds: float
    embedding_base_url: str | None
    embedding_api_key: str | None
    embedding_model: str | None
    notebook_generator: str = "deepseek"
    generation_batch_chars: int = 18_000
    generation_max_chars: int = 120_000
    allowed_extensions: tuple[str, ...] = (".pptx", ".pdf", ".docx")

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'notebook.sqlite3').as_posix()}"


settings = Settings(
    data_dir=_resolve_data_dir(),
    max_upload_bytes=int(os.getenv("NOTEBOOK_MAX_UPLOAD_MB", "50")) * 1024 * 1024,
    max_pages=max(1, int(os.getenv("NOTEBOOK_MAX_PAGES", "500"))),
    deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
    deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
    deepseek_input_cost_per_million=float(os.getenv("DEEPSEEK_INPUT_COST_PER_MILLION", "0")),
    deepseek_output_cost_per_million=float(os.getenv("DEEPSEEK_OUTPUT_COST_PER_MILLION", "0")),
    tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
    web_search_timeout_seconds=float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "20")),
    embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or None,
    embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
    embedding_model=os.getenv("EMBEDDING_MODEL") or None,
    notebook_generator=(os.getenv("NOTEBOOK_GENERATOR", "deepseek").strip().lower() or "deepseek"),
    generation_batch_chars=max(2_000, int(os.getenv("NOTEBOOK_GENERATION_BATCH_CHARS", "18000"))),
    generation_max_chars=max(10_000, int(os.getenv("NOTEBOOK_GENERATION_MAX_CHARS", "120000"))),
    allowed_extensions=tuple(
        item.strip().lower() for item in os.getenv("NOTEBOOK_ALLOWED_EXTENSIONS", ".pptx,.pdf,.docx").split(",") if item.strip()
    ) or (".pptx",),
)
