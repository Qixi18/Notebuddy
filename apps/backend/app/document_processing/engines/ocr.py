"""Optional OCR engines with explicit capability reporting.

Supported, in order of preference:
1. RapidOCR (``rapidocr_onnxruntime``) - offline ONNX engine, no system deps.
2. Tesseract via ``pytesseract`` - requires the tesseract binary.

When neither is importable the adapter must mark pages as ``needs_ocr`` rather
than pretending the page was parsed.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.document_processing.engines.pdf_text import EngineInfo

logger = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """No OCR engine is available in this environment."""


@dataclass
class OcrLine:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = "none"
    version: str = "0"
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text).strip()

    @property
    def mean_confidence(self) -> float | None:
        values = [line.confidence for line in self.lines if line.confidence is not None]
        if not values:
            return None
        return sum(values) / len(values)


def _rapidocr():
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        return RapidOCR
    except Exception:
        return None


def _pytesseract():
    try:
        import pytesseract  # type: ignore

        return pytesseract
    except Exception:
        return None


def availability() -> EngineInfo:
    rapid = _rapidocr()
    if rapid is not None:
        try:
            import rapidocr_onnxruntime as module  # type: ignore

            version = str(getattr(module, "__version__", "?"))
        except Exception:
            version = "?"
        return EngineInfo(name="rapidocr", version=version, available=True,
                          capabilities=("text", "bbox", "confidence", "offline"))
    tess = _pytesseract()
    if tess is not None:
        try:
            version = str(tess.get_tesseract_version())
        except Exception as exc:  # binary missing
            return EngineInfo(name="tesseract", version="0", available=False,
                              reason=f"tesseract binary unavailable: {exc}")
        return EngineInfo(name="tesseract", version=version, available=True,
                          capabilities=("text", "bbox", "confidence"))
    return EngineInfo(
        name="none", version="0", available=False,
        reason="未安装 OCR 引擎（rapidocr_onnxruntime 或 pytesseract+tesseract）",
    )


def recognize(image: bytes | Path, *, language: str = "chi_sim+eng",
              timeout_seconds: float = 60.0) -> OcrResult:
    info = availability()
    if not info.available:
        raise OcrUnavailable(info.reason or "OCR 引擎不可用")
    if info.name == "rapidocr":
        return _recognize_rapidocr(image)
    return _recognize_tesseract(image, language=language, timeout_seconds=timeout_seconds)


def _bbox_from_points(points: Any) -> list[float] | None:
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    except (TypeError, ValueError, IndexError):
        return None


def _recognize_rapidocr(image: bytes | Path) -> OcrResult:
    RapidOCR = _rapidocr()
    if RapidOCR is None:  # pragma: no cover - guarded by availability()
        raise OcrUnavailable("rapidocr 未安装")
    engine = RapidOCR()
    temporary: Path | None = None
    try:
        target: Any = image
        if isinstance(image, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(image)
                temporary = Path(handle.name)
            target = str(temporary)
        result, _elapsed = engine(str(target) if isinstance(target, Path) else target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    lines: list[OcrLine] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box, text = item[0], item[1]
        score = item[2] if len(item) > 2 else None
        text = str(text or "").strip()
        if not text:
            continue
        lines.append(OcrLine(
            text=text,
            bbox=_bbox_from_points(box),
            confidence=float(score) if isinstance(score, (int, float)) else None,
        ))
    version = availability().version
    return OcrResult(lines=lines, engine="rapidocr", version=version)


def _recognize_tesseract(image: bytes | Path, *, language: str, timeout_seconds: float) -> OcrResult:
    pytesseract = _pytesseract()
    if pytesseract is None:  # pragma: no cover - guarded by availability()
        raise OcrUnavailable("pytesseract 未安装")
    from PIL import Image

    if isinstance(image, bytes):
        import io

        handle = Image.open(io.BytesIO(image))
    else:
        handle = Image.open(image)
    try:
        data = pytesseract.image_to_data(
            handle, lang=language, timeout=timeout_seconds,
            output_type=pytesseract.Output.DICT,
        )
    finally:
        handle.close()
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, word in enumerate(data.get("text") or []):
        if not str(word or "").strip():
            continue
        key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        grouped.setdefault(key, []).append(index)
    lines: list[OcrLine] = []
    for indexes in grouped.values():
        words = [str(data["text"][index]).strip() for index in indexes]
        confidences = []
        for index in indexes:
            try:
                confidences.append(float(data["conf"][index]) / 100.0)
            except (TypeError, ValueError):
                continue
        left = min(int(data["left"][index]) for index in indexes)
        top = min(int(data["top"][index]) for index in indexes)
        right = max(int(data["left"][index]) + int(data["width"][index]) for index in indexes)
        bottom = max(int(data["top"][index]) + int(data["height"][index]) for index in indexes)
        lines.append(OcrLine(
            text=" ".join(words),
            bbox=[float(left), float(top), float(right), float(bottom)],
            confidence=sum(confidences) / len(confidences) if confidences else None,
        ))
    return OcrResult(
        lines=lines, engine="tesseract", version=availability().version,
        warnings=["OCR 识别结果；公式/表格结构可能丢失，请核对原始页面"],
    )
