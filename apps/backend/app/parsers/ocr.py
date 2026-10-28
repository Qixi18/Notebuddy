"""Optional OCR adapter with explicit capability and resource limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


class OCRUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRConfig:
    enabled: bool = False
    max_pages: int = 10
    language: str = "chi_sim+eng"
    timeout_seconds: float = 30.0


def config() -> OCRConfig:
    try:
        max_pages = max(1, int(os.getenv("NOTEBOOK_OCR_MAX_PAGES", "10")))
    except ValueError:
        max_pages = 10
    try:
        timeout_seconds = max(1.0, float(os.getenv("NOTEBOOK_OCR_TIMEOUT_SECONDS", "30")))
    except ValueError:
        timeout_seconds = 30.0
    return OCRConfig(
        enabled=os.getenv("NOTEBOOK_OCR_ENABLED", "").lower() in {"1", "true", "yes"},
        max_pages=max_pages,
        language=os.getenv("NOTEBOOK_OCR_LANGUAGE", "chi_sim+eng"),
        timeout_seconds=timeout_seconds,
    )


def status() -> dict[str, object]:
    settings = config()
    if not settings.enabled:
        state = "disabled"
        available = False
        provider = os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower()
    else:
        from app.document_processing.engines import pdf_text

        renderer = pdf_text.availability()
        if "render" not in renderer.capabilities:
            state = "missing_dependency"
            available = False
            provider = os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower()
        else:
            from app.document_processing.engines.ocr import availability

            engine = availability()
            provider = f"{engine.name}+{renderer.name}"
            available = engine.available
            state = "ready" if available else "missing_dependency"
    return {
        "enabled": settings.enabled,
        "available": available,
        "status": state,
        "provider": provider,
        "max_pages": settings.max_pages,
        "language": settings.language,
        "timeout_seconds": settings.timeout_seconds,
    }


def ocr_image(path: Path, *, page_number: int) -> tuple[str, str, float]:
    settings = config()
    if not settings.enabled:
        raise OCRUnavailable("OCR 未启用；请配置 NOTEBOOK_OCR_ENABLED=true 后按需重试")
    if page_number > settings.max_pages:
        raise OCRUnavailable(f"OCR 页数超过限制（最多 {settings.max_pages} 页）")
    from app.document_processing.engines import ocr as document_ocr
    try:
        result = document_ocr.recognize(
            path, language=settings.language, timeout_seconds=settings.timeout_seconds,
        )
    except Exception as exc:
        if isinstance(exc, document_ocr.OcrUnavailable):
            raise OCRUnavailable(f"OCR 执行失败：{exc}") from exc
        raise OCRUnavailable(f"OCR 执行失败：{type(exc).__name__}") from exc
    return result.text, f"ocr_{result.engine}", result.mean_confidence or (0.7 if result.text else 0.0)


def ocr_pdf_page(path: Path, *, page_number: int) -> tuple[str, str, float]:
    """Render one PDF page and pass the image through the bounded OCR adapter."""
    try:
        import fitz
    except ImportError as exc:
        raise OCRUnavailable("PDF OCR 需要安装 PyMuPDF；当前只保留 OCR 候选告警") from exc
    try:
        with fitz.open(str(path)) as document:
            if page_number < 1 or page_number > len(document):
                raise OCRUnavailable(f"PDF 页面不存在：第 {page_number} 页")
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            with NamedTemporaryFile(suffix=".png", delete=False) as output:
                image_path = Path(output.name)
            try:
                pixmap.save(str(image_path))
                return ocr_image(image_path, page_number=page_number)
            finally:
                image_path.unlink(missing_ok=True)
    except OCRUnavailable:
        raise
    except Exception as exc:
        raise OCRUnavailable(f"PDF 页面渲染失败：{exc}") from exc
