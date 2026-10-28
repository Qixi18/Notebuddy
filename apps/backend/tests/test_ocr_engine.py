from app.document_processing.engines import ocr


def test_paddle_availability_runs_model_probe_and_reports_failure(monkeypatch):
    class BrokenPaddle:
        def __init__(self, **_kwargs):
            pass

        def predict(self, _path):
            raise RuntimeError("model weights missing")

    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "paddleocr")
    monkeypatch.setattr(ocr, "_paddleocr_class", lambda: BrokenPaddle)
    monkeypatch.setattr(ocr, "_PADDLEOCR_ENGINE", None)
    monkeypatch.setattr(ocr, "_PADDLEOCR_ERROR", None)
    monkeypatch.setattr(ocr, "_PADDLEOCR_PROBED", False)

    result = ocr.availability()

    assert result.available is False
    assert "model weights missing" in (result.reason or "")


def test_paddle_availability_only_succeeds_after_probe_inference(monkeypatch):
    class WorkingPaddle:
        def __init__(self, **_kwargs):
            self.calls = 0

        def predict(self, _path):
            self.calls += 1
            return []

    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "paddleocr")
    monkeypatch.setattr(ocr, "_paddleocr_class", lambda: WorkingPaddle)
    monkeypatch.setattr(ocr, "_PADDLEOCR_ENGINE", None)
    monkeypatch.setattr(ocr, "_PADDLEOCR_ERROR", None)
    monkeypatch.setattr(ocr, "_PADDLEOCR_PROBED", False)

    result = ocr.availability()

    assert result.available is True
    assert ocr._PADDLEOCR_ENGINE.calls == 1
    assert ocr.availability().available is True
    assert ocr._PADDLEOCR_ENGINE.calls == 1


def test_manual_ocr_status_accepts_pdfium_without_pymupdf(monkeypatch):
    import pytest

    pytest.importorskip("pypdfium2")
    from app.document_processing.engines import pdf_text
    from app.parsers.ocr import status

    monkeypatch.setenv("NOTEBOOK_OCR_ENABLED", "true")
    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "rapidocr")
    monkeypatch.setattr(pdf_text, "_pymupdf", lambda: None)
    monkeypatch.setattr(
        ocr, "availability",
        lambda **_kwargs: ocr.EngineInfo(
            name="rapidocr", version="1", available=True, capabilities=("text", "bbox"),
        ),
    )

    result = status()

    assert result["available"] is True
    assert result["provider"] == "rapidocr+pypdf+pdfium"
