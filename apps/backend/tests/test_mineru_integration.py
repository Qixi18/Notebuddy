"""Regression checks for content fidelity and OCR retries with MinerU enabled."""

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
