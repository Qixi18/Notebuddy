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
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.document_processing.engines.pdf_text import EngineInfo

logger = logging.getLogger(__name__)
_PADDLEOCR_CLASS: Any = None
_PADDLEOCR_ENGINE: Any = None
_PADDLEOCR_ERROR: str | None = None
_PADDLEOCR_PROBED = False
_RAPIDOCR_ENGINE: Any = None
_RAPIDOCR_ERROR: str | None = None
_RAPIDOCR_PROBED = False
_PADDLEOCR_LOCK = threading.Lock()
_RAPIDOCR_LOCK = threading.Lock()


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
    if _PADDLEOCR_ERROR is None and _paddleocr_class() is not None:
        return "paddleocr"
    if _RAPIDOCR_ERROR is None and _rapidocr() is not None:
        return "rapidocr"
    if _pytesseract() is not None:
        return "tesseract"
    return "none"


def availability(*, probe: bool = True) -> EngineInfo:
    global _PADDLEOCR_ERROR, _RAPIDOCR_ERROR
    selected = _selected_engine()
    if selected == "paddleocr":
        PaddleOCR = _paddleocr_class()
        if PaddleOCR is not None:
            if _PADDLEOCR_ERROR:
                return EngineInfo(name="paddleocr", version="0", available=False,
                                  reason=_PADDLEOCR_ERROR)
            if probe:
                try:
                    _initialize_paddleocr(probe=True)
                except Exception as exc:
                    _PADDLEOCR_ERROR = f"PaddleOCR 初始化或预检推理失败：{type(exc).__name__}: {exc}"
                    if os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower() == "auto":
                        fallback = _selected_engine()
                        if fallback not in {"none", "paddleocr"}:
                            return availability(probe=probe)
                    return EngineInfo(name="paddleocr", version="0", available=False,
                                      reason=_PADDLEOCR_ERROR)
            try:
                from importlib.metadata import version

                paddle_version = version("paddleocr")
            except Exception:
                paddle_version = "?"
            capabilities = ("text", "bbox", "confidence", "layout", "offline")
            if not probe and _PADDLEOCR_ENGINE is None:
                capabilities += ("inference_not_probed",)
            return EngineInfo(name="paddleocr", version=paddle_version, available=True,
                              capabilities=capabilities)
        return EngineInfo(name="paddleocr", version="0", available=False,
                          reason="未安装 PaddleOCR 及其运行依赖")
    if selected == "rapidocr":
        rapid = _rapidocr()
        if rapid is None:
            return EngineInfo(name="rapidocr", version="0", available=False,
                              reason="未安装 rapidocr_onnxruntime")
        if _RAPIDOCR_ERROR:
            return EngineInfo(name="rapidocr", version="0", available=False,
                              reason=_RAPIDOCR_ERROR)
        if probe:
            try:
                _initialize_rapidocr(probe=True)
            except Exception as exc:
                _RAPIDOCR_ERROR = f"RapidOCR 初始化或预检推理失败：{type(exc).__name__}: {exc}"
                if os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower() == "auto":
                    fallback = _selected_engine()
                    if fallback not in {"none", "rapidocr"}:
                        return availability(probe=probe)
                return EngineInfo(name="rapidocr", version="0", available=False,
                                  reason=_RAPIDOCR_ERROR)
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

    reasons = [reason for reason in (_PADDLEOCR_ERROR, _RAPIDOCR_ERROR) if reason]
    return EngineInfo(name="none", version="0", available=False,
                      reason="；".join(reasons) or
                      "未安装 PaddleOCR、RapidOCR 或 Tesseract OCR 引擎")

def recognize(image: bytes | Path, *, language: str = "chi_sim+eng",
              timeout_seconds: float = 60.0) -> OcrResult:
    last_error: Exception | None = None
    for _attempt in range(3):
        info = availability()
        if not info.available:
            if last_error:
                raise OcrUnavailable(f"自动选择的 OCR 引擎均不可用：{last_error}; {info.reason}")
            raise OcrUnavailable(info.reason or "OCR 引擎不可用")
        try:
            if info.name == "paddleocr":
                return _recognize_paddleocr(image)
            if info.name == "rapidocr":
                return _recognize_rapidocr(image)
            return _recognize_tesseract(image, language=language, timeout_seconds=timeout_seconds)
        except Exception as exc:
            last_error = exc
            if info.name == "paddleocr":
                global _PADDLEOCR_ENGINE, _PADDLEOCR_ERROR
                _PADDLEOCR_ENGINE = None
                _PADDLEOCR_ERROR = f"PaddleOCR 推理失败：{type(exc).__name__}: {exc}"
            elif info.name == "rapidocr":
                global _RAPIDOCR_ENGINE, _RAPIDOCR_ERROR
                _RAPIDOCR_ENGINE = None
                _RAPIDOCR_ERROR = f"RapidOCR 推理失败：{type(exc).__name__}: {exc}"
            if os.getenv("NOTEBOOK_OCR_ENGINE", "auto").strip().lower() != "auto":
                raise OcrUnavailable(str(last_error)) from exc
    raise OcrUnavailable(str(last_error or "OCR 推理失败"))


def _probe_image() -> Path:
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        path = Path(handle.name)
    Image.new("RGB", (32, 32), "white").save(path, format="PNG")
    return path


def _initialize_paddleocr(*, probe: bool) -> Any:
    global _PADDLEOCR_ENGINE, _PADDLEOCR_PROBED
    started = time.perf_counter()
    was_initialized = _PADDLEOCR_ENGINE is not None and _PADDLEOCR_PROBED
    PaddleOCR = _paddleocr_class()
    if PaddleOCR is None:
        raise OcrUnavailable("未安装 PaddleOCR 或 PaddlePaddle 运行时")
    if _PADDLEOCR_ENGINE is None:
        with _PADDLEOCR_LOCK:
            if _PADDLEOCR_ENGINE is None:
                lang = os.getenv("NOTEBOOK_PADDLEOCR_LANG", "ch").strip() or "ch"
                _PADDLEOCR_ENGINE = PaddleOCR(lang=lang, ocr_version="PP-OCRv6")
    if probe and not _PADDLEOCR_PROBED:
        with _PADDLEOCR_LOCK:
            if not _PADDLEOCR_PROBED:
                image = _probe_image()
                try:
                    _PADDLEOCR_ENGINE.predict(str(image))
                    _PADDLEOCR_PROBED = True
                finally:
                    image.unlink(missing_ok=True)
    if probe and not was_initialized:
        logger.info("ocr_engine_ready engine=paddleocr init_and_probe_seconds=%.3f",
                    time.perf_counter() - started)
    return _PADDLEOCR_ENGINE


def _initialize_rapidocr(*, probe: bool) -> Any:
    global _RAPIDOCR_ENGINE, _RAPIDOCR_PROBED
    started = time.perf_counter()
    was_initialized = _RAPIDOCR_ENGINE is not None and _RAPIDOCR_PROBED
    RapidOCR = _rapidocr()
    if RapidOCR is None:
        raise OcrUnavailable("rapidocr_onnxruntime 未安装")
    if _RAPIDOCR_ENGINE is None:
        with _RAPIDOCR_LOCK:
            if _RAPIDOCR_ENGINE is None:
                _RAPIDOCR_ENGINE = RapidOCR()
    if probe and not _RAPIDOCR_PROBED:
        with _RAPIDOCR_LOCK:
            if not _RAPIDOCR_PROBED:
                image = _probe_image()
                try:
                    _RAPIDOCR_ENGINE(str(image))
                    _RAPIDOCR_PROBED = True
                finally:
                    image.unlink(missing_ok=True)
    if probe and not was_initialized:
        logger.info("ocr_engine_ready engine=rapidocr init_and_probe_seconds=%.3f",
                    time.perf_counter() - started)
    return _RAPIDOCR_ENGINE


def _recognize_paddleocr(image: bytes | Path) -> OcrResult:
    engine = _initialize_paddleocr(probe=False)

    temporary: Path | None = None
    try:
        if isinstance(image, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(image)
                temporary = Path(handle.name)
            target = str(temporary)
        else:
            target = str(image)
        started = time.perf_counter()
        results = engine.predict(target)
        logger.info("ocr_inference_finished engine=paddleocr elapsed_seconds=%.3f",
                    time.perf_counter() - started)
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
    engine = _initialize_rapidocr(probe=False)
    temporary: Path | None = None
    try:
        target: Any = image
        if isinstance(image, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(image)
                temporary = Path(handle.name)
            target = str(temporary)
        started = time.perf_counter()
        result, _elapsed = engine(str(target) if isinstance(target, Path) else target)
        logger.info("ocr_inference_finished engine=rapidocr elapsed_seconds=%.3f",
                    time.perf_counter() - started)
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
