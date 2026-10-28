"""Regression checks for content fidelity and OCR retries with MinerU enabled."""

import base64
import json
from types import SimpleNamespace

import pytest

from app.api.v1 import materials
from app.core.config import settings
from app.db.models import DocumentPage, MaterialPage
from app.document_processing.adapters.mineru import _map_item
from tests.notebook_fixtures import (
    make_asset,
    make_material,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


def test_standard_mineru_vlm_enables_utf8_locale_on_windows(monkeypatch):
    import locale

    from app.document_processing.adapters import mineru

    state = {"locale": "Chinese (Simplified)_China.936"}
    calls = []

    def fake_setlocale(category, value=None):
        if value is None:
            return state["locale"]
        calls.append(value)
        state["locale"] = "Chinese (Simplified)_China.utf8"
        return state["locale"]

    monkeypatch.setattr(mineru.os, "name", "nt")
    monkeypatch.setattr(locale, "setlocale", fake_setlocale)
    mineru._ensure_windows_vlm_utf8_locale("standard")
    assert calls == [".UTF-8"]


def map_item(kind, content):
    return _map_item(
        {"type": kind, "content": content}, block_id="test-p1-b1",
        page_number=1, order=0, global_order=0, asset_id="asset-1",
    )


def test_mineru_table_keeps_rows_and_cells():
    blocks = map_item("table", {"html": (
        "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td><b>A</b></td><td>1 &lt; 2</td></tr></table>"
    )})
    assert len(blocks) == 1
    assert blocks[0].table.rows == [["Name", "Value"], ["A", "1 < 2"]]


def test_mineru_unstructured_table_keeps_text_with_warning():
    blocks = map_item("table", {"html": "<div>Unstructured table content</div>"})
    assert blocks[0].text == "Unstructured table content"
    assert blocks[0].warnings


def test_mineru_equation_keeps_literal_inequalities():
    latex = r"a<b<c \quad x \in \mathbb{R}"
    blocks = map_item("equation_interline", {"math_content": latex})
    assert blocks[0].latex == latex


def test_mineru_spans_keep_spaces_between_words():
    blocks = map_item("paragraph", {"paragraph_content": [
        {"type": "text", "content": "Hello "},
        {"type": "text", "content": "world "},
        {"type": "equation_inline", "content": "x<y"},
    ]})
    assert blocks[0].text == "Hello world x<y"


def test_mineru_image_sidecar_is_saved_with_bbox_and_roundtrips(tmp_path, monkeypatch):
    from app.document_processing.ir import FigureData

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    payload = b"\x89PNG\r\n\x1a\nsmall-image"
    stored = {}

    def store(data, suffix):
        key = f"derived/figures/asset/run/hash{suffix}"
        stored[key] = data
        return key

    raw = SimpleNamespace(image_base64="data:image/png;base64," + base64.b64encode(payload).decode())
    blocks = _map_item(
        {"type": "image", "bbox": [0.1, 0.2, 0.8, 0.9], "content": {"image_caption": ["流程图"]}},
        block_id="image-1", page_number=1, order=0, global_order=0, asset_id="asset-1",
        raw_block=raw, image_store=store,
    )
    block = blocks[0]
    assert block.figure and block.figure.image_key == "derived/figures/asset/run/hash.png"
    assert block.bbox == [100.0, 200.0, 800.0, 900.0]
    assert stored[block.figure.image_key] == payload
    restored = FigureData.from_dict(block.figure.to_dict())
    assert restored and restored.image_key == block.figure.image_key


def test_mineru_vision_enrichment_uses_saved_crop(monkeypatch, tmp_path):
    from app.document_processing.adapters import mineru
    from app.document_processing.ir import FigureData

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setenv("NOTEBOOK_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("NOTEBOOK_VISION_MODEL", "vision-test")
    image_key = "derived/figures/a/r/test.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image-bytes")
    seen = []

    def describe(image, *, mime):
        seen.append((image, mime))
        return SimpleNamespace(
            description="流程图包含三个步骤", latex=None,
            figure={"kind": "diagram", "nodes": ["开始", "处理", "结束"],
                    "edges": ["开始 -> 处理"]}, uncertain=False,
        )

    monkeypatch.setattr("app.document_processing.engines.vision.describe", describe)
    figure = FigureData(image_key=image_key, uncertain=True)
    blocks = mineru._enrich_mineru_figure(
        figure, image_key, asset_id="asset-1", page_number=3, order=4,
        global_order=9, bbox=[100, 200, 800, 900],
    )
    assert seen == [(b"image-bytes", "image/png")]
    assert len(blocks) == 1
    enriched = blocks[0]
    assert enriched.figure and enriched.figure.description == "流程图包含三个步骤"
    assert enriched.figure.nodes == ["开始", "处理", "结束"]
    assert enriched.figure.uncertain is False
    assert enriched.page_number == 3 and enriched.order == 4
    assert enriched.source and enriched.source.asset_id == "asset-1"
    assert enriched.source.bbox == [100, 200, 800, 900]


def test_mineru_vision_emits_searchable_equation_block(monkeypatch, tmp_path):
    from app.document_processing.adapters import mineru
    from app.document_processing.ir import FigureData

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setenv("NOTEBOOK_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("NOTEBOOK_VISION_MODEL", "vision-test")
    image_key = "derived/figures/a/r/formula.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image-bytes")
    monkeypatch.setattr("app.document_processing.engines.vision.describe", lambda *_a, **_k: SimpleNamespace(
        description="电阻公式", latex="V=IR", table=None,
        figure={"kind": "formula", "nodes": [], "edges": []},
        uncertain=False, warnings=[],
    ))
    blocks = mineru._enrich_mineru_figure(
        FigureData(image_key=image_key), image_key, asset_id="asset-1", page_number=2,
        order=3, global_order=5, bbox=[10, 20, 30, 40],
    )
    equation = next(block for block in blocks if block.type == "equation")
    assert equation.latex == "V=IR"
    assert equation.page_number == 2 and equation.global_order == 5
    assert equation.source and equation.source.asset_id == "asset-1"


def test_vision_engine_sends_openai_compatible_image_and_parses_json(monkeypatch):

    from app.document_processing.engines import vision

    monkeypatch.setenv("NOTEBOOK_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("NOTEBOOK_VISION_API_KEY", "secret-test")
    monkeypatch.setenv("NOTEBOOK_VISION_MODEL", "vision-test")
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "description": "识别出一个电路图", "latex": "V=IR", "table": None,
                "figure": {"kind": "circuit", "nodes": ["R1"], "edges": ["V -> R1"]},
                "uncertain": False,
            }, ensure_ascii=False)}}]}

    class Client:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            captured.update(url=url, payload=json, headers=headers)
            return Response()

    monkeypatch.setattr("httpx.Client", Client)
    result = vision.describe(b"png-bytes", mime="image/png")
    assert captured["url"] == "https://vision.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-test"
    assert captured["payload"]["messages"][0]["content"][1]["image_url"]["url"].endswith(
        "cG5nLWJ5dGVz"
    )
    assert result.description == "识别出一个电路图"
    assert result.latex == "V=IR"
    assert result.figure["kind"] == "circuit"
    assert result.uncertain is False


def test_document_figure_endpoint_serves_only_current_run_image(session, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db.database import get_db
    from app.db.models import DocumentBlock
    from app.document_processing.ir import FigureData
    from app.main import app

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    book = make_notebook(session, None)
    asset = make_asset(session, book)
    run = persist_ir(session, book, asset)
    image_key = f"derived/figures/{asset.id}/{run.id}/abc123.png"
    image_path = tmp_path / image_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\ntest")
    block = session.query(DocumentBlock).filter_by(parse_run_id=run.id).first()
    block.figure_json = __import__("json").dumps(FigureData(image_key=image_key).to_dict())
    session.commit()

    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/assets/{asset.id}/document/figures/abc123?run_id={run.id}"
            )
            assert response.status_code == 200
            assert response.content == image_path.read_bytes()
            assert response.headers["content-type"] == "image/png"

            evidence = client.get(
                f"/api/v1/assets/{asset.id}/document/pages/1/evidence?run_id={run.id}"
            )
            assert evidence.status_code == 200
            figure_block = next(item for item in evidence.json() if item["figure"])
            assert figure_block["figure"]["image_key"] == (
                f"/api/v1/assets/{asset.id}/document/figures/abc123?run_id={run.id}"
            )

            run.status = "failed"
            session.commit()
            rejected = client.get(
                f"/api/v1/assets/{asset.id}/document/figures/abc123?run_id={run.id}"
            )
            assert rejected.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_mineru_ocr_retry_does_not_require_separate_ocr_engine(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "mineru")
    monkeypatch.setattr(materials, "ensure_material", lambda *_: SimpleNamespace(id="material-1"))
    monkeypatch.setattr(materials.mineru_adapter, "availability", lambda: {"available": True})
    job = SimpleNamespace(id="job-1")
    calls = []
    monkeypatch.setattr(materials, "reparse_material", lambda mid, db: calls.append(mid) or job)

    def unexpected_ocr_check():
        raise AssertionError("MinerU must not depend on the separate OCR capability")

    monkeypatch.setattr(materials, "ocr_status", unexpected_ocr_check)
    assert materials.request_material_ocr("material-1", object()) is job
    assert calls == ["material-1"]


def test_native_ocr_retry_uses_current_ir_pages(session, monkeypatch, tmp_path):
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "native")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(materials, "ocr_status", lambda: {"status": "ready"})
    book = make_notebook(session, None)
    asset = make_asset(session, book)
    material = make_material(session, book, asset)
    run = persist_ir(session, book, asset)
    page = session.query(DocumentPage).filter_by(parse_run_id=run.id).one()
    page.status = "needs_ocr"
    session.commit()
    assert session.query(MaterialPage).count() == 0
    job = materials.request_material_ocr(material.id, session)
    assert job.kind == "ocr_material"
    assert job.status == "pending"


def test_pdf_preview_is_available_before_render_is_cached(monkeypatch):
    page = SimpleNamespace(
        page_number=1, status="needs_ocr", extraction="none", width=600,
        height=800, rotation=0, confidence=None, warnings=[], text="", render_key=None,
    )
    monkeypatch.setattr(materials, "load_ir", lambda *_: SimpleNamespace(pages=[page], sections=[]))
    monkeypatch.setattr(materials, "_run_payload", lambda _: {})
    run = SimpleNamespace(asset_id="asset-1", doc_type="pdf")
    payload = materials._document_payload(None, run)
    assert payload["pages"][0]["render_url"] == (
        "/api/v1/assets/asset-1/document/pages/1/render"
    )


def test_pdfium_preview_works_without_pymupdf(monkeypatch, tmp_path):
    pytest.importorskip("pypdfium2")
    from pypdf import PdfWriter

    from app.document_processing.engines import pdf_text

    path = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    with path.open("wb") as handle:
        writer.write(handle)
    monkeypatch.setattr(pdf_text, "_pymupdf", lambda: None)
    png = pdf_text.render_pdf_page(path, 1)
    assert png is not None and png.startswith(b"\x89PNG\r\n\x1a\n")
    assert pdf_text.render_pdf_page(path, 2) is None


def test_model_inference_does_not_hold_sqlite_write_lock(monkeypatch, tmp_path):
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.database import Base
    from app.document_processing import service
    from tests.notebook_fixtures import simple_ir

    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "mineru")
    db_path = tmp_path / "isolated.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            book = make_notebook(db, None)
            asset = make_asset(db, book)
            run = service.create_parse_run(db, asset=asset)
            db.commit()

            def slow_parser(_path, context):
                with sqlite3.connect(db_path, timeout=0.2) as other:
                    status = other.execute(
                        "SELECT status FROM document_parse_runs WHERE id=?", (run.id,),
                    ).fetchone()[0]
                    assert status == "running"
                    other.execute(
                        "UPDATE document_parse_runs SET config_version=config_version WHERE id=?",
                        (run.id,),
                    )
                return simple_ir(asset.id, context.parse_run_id)

            monkeypatch.setattr(service, "parse_with_mineru", slow_parser)
            outcome = service.execute_parse_run(db, run.id, source_path=tmp_path / "source.pdf")
            assert outcome.run.status == "completed"
    finally:
        engine.dispose()
