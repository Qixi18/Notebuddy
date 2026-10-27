"""Optional OCR engines with explicit capability reporting.

Supported, in order of preference:
1. PaddleOCR PP-OCRv6 (optional PaddleX/PaddlePaddle installation).
2. RapidOCR (``rapidocr_onnxruntime``) - offline ONNX engine, no system deps.
3. Tesseract via ``pytesseract`` - requires the tesseract binary.

When neither is importable the adapter must mark pages as ``needs_ocr`` rather
than pretending the page was parsed.
"""

from __future__ import annotations

import logging
import os
import threading
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.document_processing.engines.pdf_text import EngineInfo

logger = logging.getLogger(__name__)
_PADDLEOCR_CLASS: Any = None
_PADDLEOCR_ENGINE: Any = None
_PADDLEOCR_LOCK = threading.Lock()


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


def _paddleocr_class():
    global _PADDLEOCR_CLASS
    if _PADDLEOCR_CLASS is not None:
        return _PADDLEOCR_CLASS
    try:
        import paddle  # type: ignore # noqa: F401
        from paddleocr import PaddleOCR  # type: ignore

        _PADDLEOCR_CLASS = PaddleOCR
        return PaddleOCR
    except Exception:
        return None


def _selected_engine() -> str:
    requested = os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower()
    if requested in {"paddleocr", "rapidocr", "tesseract", "none"}:
        return requested
    if requested != "auto":
        logger.warning("Unknown NOTEBOOK_OCR_ENGINE=%r; using automatic selection", requested)
    if _paddleocr_class() is not None:
        return "paddleocr"
    if _rapidocr() is not None:
        return "rapidocr"
    if _pytesseract() is not None:
        return "tesseract"
    return "none"


def availability() -> EngineInfo:
    selected = _selected_engine()
    if selected == "paddleocr":
        PaddleOCR = _paddleocr_class()
        if PaddleOCR is not None:
            try:
                from importlib.metadata import version

                paddle_version = version("paddleocr")
            except Exception:
                paddle_version = "?"
            return EngineInfo(name="paddleocr", version=paddle_version, available=True,
                              capabilities=("text", "bbox", "confidence", "layout", "offline"))
        return EngineInfo(name="paddleocr", version="0", available=False,
                          reason="未安装 PaddleOCR 及其运行依赖")
    if selected == "rapidocr":
        rapid = _rapidocr()
        if rapid is None:
            return EngineInfo(name="rapidocr", version="0", available=False,
                              reason="未安装 rapidocr_onnxruntime")
        try:
            import rapidocr_onnxruntime as module  # type: ignore

            version = str(getattr(module, "__version__", "?"))
        except Exception:
            version = "?"
        return EngineInfo(name="rapidocr", version=version, available=True,
                          capabilities=("text", "bbox", "confidence", "offline"))
    if selected == "tesseract":
        tess = _pytesseract()
        if tess is None:
            return EngineInfo(name="tesseract", version="0", available=False,
                              reason="未安装 pytesseract")
        try:
            version = str(tess.get_tesseract_version())
        except Exception as exc:
            return EngineInfo(name="tesseract", version="0", available=False,
                              reason=f"tesseract binary unavailable: {exc}")
        return EngineInfo(name="tesseract", version=version, available=True,
                          capabilities=("text", "bbox", "confidence"))
    if selected == "none":
        return EngineInfo(name="none", version="0", available=False,
                          reason="OCR 已通过 NOTEBOOK_OCR_ENGINE=none 关闭")

    return EngineInfo(name="none", version="0", available=False,
                      reason="未安装 PaddleOCR、RapidOCR 或 Tesseract OCR 引擎")

def recognize(image: bytes | Path, *, language: str = "chi_sim+eng",
              timeout_seconds: float = 60.0) -> OcrResult:
    info = availability()
    if not info.available:
        raise OcrUnavailable(info.reason or "OCR 引擎不可用")
    if info.name == "paddleocr":
        return _recognize_paddleocr(image)
    if info.name == "rapidocr":
        return _recognize_rapidocr(image)
    return _recognize_tesseract(image, language=language, timeout_seconds=timeout_seconds)


def _recognize_paddleocr(image: bytes | Path) -> OcrResult:
    global _PADDLEOCR_ENGINE
    PaddleOCR = _paddleocr_class()
    if PaddleOCR is None:  # pragma: no cover - guarded by availability()
        raise OcrUnavailable("PaddleOCR 未安装")
    if _PADDLEOCR_ENGINE is None:
        with _PADDLEOCR_LOCK:
            if _PADDLEOCR_ENGINE is None:
                lang = os.getenv("NOTEBOOK_PADDLEOCR_LANG", "ch").strip() or "ch"
                _PADDLEOCR_ENGINE = PaddleOCR(lang=lang, ocr_version="PP-OCRv6")

    temporary: Path | None = None
    try:
        if isinstance(image, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(image)
                temporary = Path(handle.name)
            target = str(temporary)
        else:
            target = str(image)
        results = _PADDLEOCR_ENGINE.predict(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    lines: list[OcrLine] = []
    for result in results or []:
        payload = getattr(result, "json", None)
        if callable(payload):
            payload = payload()
        if not isinstance(payload, dict):
            payload = getattr(result, "res", None)
        if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
            payload = payload["res"]
        if not isinstance(payload, dict):
            continue
        texts = payload.get("rec_texts")
        scores = payload.get("rec_scores")
        boxes = payload.get("rec_boxes")
        texts = [] if texts is None else texts
        scores = [] if scores is None else scores
        boxes = [] if boxes is None else boxes
        if hasattr(texts, "tolist"):
            texts = texts.tolist()
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if hasattr(boxes, "tolist"):
            boxes = boxes.tolist()
        if not isinstance(texts, (list, tuple)):
            continue
        for index, raw_text in enumerate(texts):
            text = str(raw_text or "").strip()
            if not text:
                continue
            score = scores[index] if isinstance(scores, (list, tuple)) and index < len(scores) else None
            box = boxes[index] if isinstance(boxes, (list, tuple)) and index < len(boxes) else None
            try:
                confidence = float(score) if score is not None else None
            except (TypeError, ValueError):
                confidence = None
            normalized_box = None
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                try:
                    normalized_box = [float(value) for value in box[:4]]
                except (TypeError, ValueError):
                    normalized_box = None
            lines.append(OcrLine(text=text, bbox=normalized_box, confidence=confidence))

    try:
        from importlib.metadata import version

        engine_version = version("paddleocr")
    except Exception:
        engine_version = "?"
    return OcrResult(lines=lines, engine="paddleocr", version=engine_version)


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
