"""Document Processing service: ParseRun lifecycle, versions, backfill, render."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.db.models import (
    DocumentBlock,
    DocumentChunk,
    DocumentPage,
    DocumentParseRun,
    MaterialPage,
    PageBlock,
)
from app.document_processing.service import (
    create_parse_run,
    current_run,
    execute_parse_run,
    load_ir,
    page_render,
    rebuild_views,
)
from tests.notebook_fixtures import make_asset, make_course, make_material, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]

pymupdf = pytest.importorskip("pymupdf")


def _write_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Chapter 1 Limits", fontsize=22)
    page.insert_text((72, 130), "The limit of f(x) as x approaches a is L.", fontsize=11)
    page.insert_text((72, 150), "It is defined for every neighbourhood of L.", fontsize=11)
    page.insert_text((72, 170), "A function can fail to have a limit when left and right differ.",
                     fontsize=11)
    page.insert_text((72, 190), "Limits are the foundation of derivatives and integrals.",
                     fontsize=11)
    page.insert_text((72, 210), "Every continuous function has a limit at interior points.",
                     fontsize=11)
    document.save(str(path))
    document.close()


def test_execute_parse_run_persists_evidence_and_views(session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "originals").mkdir()
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, name="limits.pdf")
    path = tmp_path / "originals" / asset.storage_key.split("/")[-1]
    _write_pdf(path)
    asset.storage_key = f"originals/{path.name}"
    session.commit()

    run = create_parse_run(session, asset=asset)
    outcome = execute_parse_run(session, run.id, source_path=path, title="极限")
    session.commit()
    assert outcome.run.status == "completed"
    assert outcome.ir.quality.generation_allowed is True
    pages = session.query(DocumentPage).filter_by(parse_run_id=run.id).all()
    blocks = session.query(DocumentBlock).filter_by(parse_run_id=run.id).all()
    chunks = session.query(DocumentChunk).filter_by(parse_run_id=run.id).all()
    assert pages and blocks and chunks
    assert outcome.run.is_current is True
    assert current_run(session, asset.id).id == run.id

    rendered = page_render(session, run, 1)
    assert rendered is not None and rendered.is_file()


def test_reparse_creates_new_version_and_keeps_old(session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "originals").mkdir()
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, name="limits.pdf")
    path = tmp_path / "originals" / asset.storage_key.split("/")[-1]
    _write_pdf(path)
    asset.storage_key = f"originals/{path.name}"
    first = create_parse_run(session, asset=asset)
    execute_parse_run(session, first.id, source_path=path)
    session.commit()

    second = create_parse_run(session, asset=asset, reparse=True)
    execute_parse_run(session, second.id, source_path=path)
    session.commit()
    runs = session.query(DocumentParseRun).filter_by(asset_id=asset.id).all()
    assert len(runs) == 2
    assert first.is_current is False
    assert second.is_current is True
    assert current_run(session, asset.id).id == second.id


def test_rebuild_views_is_idempotent(session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "originals").mkdir()
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, name="limits.pdf")
    path = tmp_path / "originals" / asset.storage_key.split("/")[-1]
    _write_pdf(path)
    asset.storage_key = f"originals/{path.name}"
    run = create_parse_run(session, asset=asset)
    execute_parse_run(session, run.id, source_path=path)
    session.commit()
    first_count = session.query(DocumentChunk).filter_by(parse_run_id=run.id).count()
    rebuild_views(session, run.id)
    rebuild_views(session, run.id)
    session.commit()
    assert session.query(DocumentChunk).filter_by(parse_run_id=run.id).count() == first_count
    loaded = load_ir(session, run.id)
    assert loaded.pages[0].blocks


def test_backfill_imports_legacy_material_pages(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, name="legacy.pdf")
    material = make_material(session, book, asset, title="旧资料")
    page = MaterialPage(
        material_id=material.id, page_number=1, title="第一页",
        raw_text="极限的定义与性质。极限是微积分的基础概念。" * 5,
        parse_status="parsed", location_label="第 1 页",
    )
    session.add(page)
    session.flush()
    session.add(PageBlock(
        page_id=page.id, block_type="text",
        content="极限的定义与性质。极限是微积分的基础概念。" * 5,
        position=0, extraction_method="native_text", confidence=1.0,
    ))
    session.commit()

    from app.migration.document_backfill import backfill

    report = backfill(session)
    session.commit()
    assert report["materials"]["imported"] == 1
    run = current_run(session, asset.id)
    assert run is not None
    assert run.parser_name == "legacy-material-pages"
    assert session.query(DocumentBlock).filter_by(parse_run_id=run.id).count() == 1
    # Idempotent.
    report_again = backfill(session)
    assert report_again["materials"]["imported"] == 0
    assert report_again["materials"]["skipped_current"] >= 1
