"""Document Processing service: ParseRun lifecycle, versions, backfill, render."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.db.models import (
    DocumentBlock,
    DocumentChunk,
    DocumentPage,
    DocumentParseRun,
    MaterialPage,
    PageBlock,
)
from app.document_processing.ir import BlockIR, FigureData, SectionIR, SourceSpan, TableData
from app.document_processing.service import (
    create_parse_run,
    current_run,
    execute_parse_run,
    load_ir,
    page_render,
    persist_existing_ir,
    rebuild_views,
)
from tests.notebook_fixtures import make_asset, make_course, make_material, make_notebook, simple_ir

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


def _write_illustrated_pdf(path: Path) -> None:
    image = Image.new("RGB", (160, 120), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Chapter 1 Limits", fontsize=22)
    page.insert_text((72, 130), "Limits are a foundation of calculus and analysis.", fontsize=12)
    page.insert_text((72, 160), "A function approaches a value near a chosen point.", fontsize=12)
    page.insert_image(pymupdf.Rect(72, 210, 232, 330), stream=image_buffer.getvalue())
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


def test_execute_parse_run_persists_embedded_figure_without_vision(
    session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "native")
    (tmp_path / "originals").mkdir()
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, name="illustrated.pdf")
    path = tmp_path / "originals" / "illustrated.pdf"
    _write_illustrated_pdf(path)

    run = create_parse_run(session, asset=asset)
    outcome = execute_parse_run(
        session, run.id, source_path=path, ocr_available=False, vision_available=False,
    )
    session.commit()

    figure_blocks = [
        block for page in outcome.ir.pages for block in page.blocks if block.figure
    ]
    assert len(figure_blocks) == 1
    image_key = figure_blocks[0].figure.image_key
    assert image_key and image_key.startswith(f"derived/figures/{asset.id}/{run.id}/")
    assert (tmp_path / image_key).is_file()
    restored = load_ir(session, run.id)
    restored_block = next(
        block for page in restored.pages for block in page.blocks
        if block.block_id == figure_blocks[0].block_id
    )
    restored_figure = restored_block.figure
    assert restored_figure and restored_figure.image_key == image_key


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


def test_document_ir_round_trip_preserves_canonical_fields(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book, sha="a" * 64)
    ir = simple_ir(asset.id, "round-trip-run")
    ir.warnings = ["文档级警告：存在低置信度页面"]
    page = ir.pages[0]
    page.page_id = "logical-page-cover"
    page.warnings = ["页面方向经过自动校正"]
    page.rotation = 90
    page.width, page.height = 842, 595
    original_block = page.blocks[0]
    original_block.source = SourceSpan(
        asset_id=asset.id, page_number=1, bbox=[0.1, 0.2, 0.8, 0.9],
        render_key="derived/render/cover.png", location_label="封面标题区域",
    )
    original_block.warnings = ["标题 OCR 置信度偏低"]
    table = BlockIR(
        block_id="table-round-trip", page_number=1, order=30, global_order=30,
        type="table", text="真值表",
        table=TableData(rows=[["A", "B"], ["0", "1"]], header_rows=1),
        source=SourceSpan(asset.id, 1, [0.1, 0.3, 0.9, 0.7], "render/table.png", "表格"),
        extraction="mineru", confidence=0.84, warnings=["单元格边界需核对"],
    )
    figure = BlockIR(
        block_id="figure-round-trip", page_number=1, order=31, global_order=31,
        type="figure", text="电路图", latex="x^2 + y^2",
        figure=FigureData(kind="circuit", description="待核验的电路", nodes=["A", "B"],
                          edges=["A->B"], uncertain=True, image_key="derived/f.png"),
        source=SourceSpan(asset.id, 1, [0.2, 0.4, 0.7, 0.8], None, "图 1"),
        extraction="vision", confidence=0.51, warnings=["电路语义未经人工验证"],
    )
    page.blocks.extend([table, figure])
    ir.sections = [SectionIR(
        section_id="round-trip-section", order=0, title="内容", level=1,
        page_start=1, page_end=1,
        block_ids=[block.block_id for block in page.blocks],
    )]

    persisted = persist_existing_ir(session, asset=asset, document=ir).ir
    loaded = load_ir(session, persisted.parse_run_id)

    expected = persisted.to_dict()
    actual = loaded.to_dict()
    assert actual["pages"] == expected["pages"], [
        {
            "page": {
                key: (epage[key], apage[key]) for key in epage
                if epage[key] != apage[key]
            },
            "blocks": [
                {key: (eblock[key], ablock[key]) for key in eblock
                 if eblock[key] != ablock[key]}
                for eblock, ablock in zip(epage["blocks"], apage["blocks"], strict=True)
                if eblock != ablock
            ],
        }
        for epage, apage in zip(expected["pages"], actual["pages"], strict=True)
        if epage != apage
    ]
    assert actual == expected
    assert loaded.compute_fingerprint() == persisted.fingerprint
    assert loaded.pages[0].page_id == "logical-page-cover"


def test_legacy_rows_without_new_metadata_remain_readable(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    run = persist_existing_ir(session, asset=asset, document=simple_ir(asset.id, "legacy")).run
    page = session.query(DocumentPage).filter_by(parse_run_id=run.id).one()
    block = session.query(DocumentBlock).filter_by(parse_run_id=run.id).first()
    page.logical_page_id = None
    block.source_json = None
    session.flush()

    loaded = load_ir(session, run.id)
    assert loaded.pages[0].page_id == "p1"
    assert loaded.pages[0].blocks[0].source.asset_id == asset.id


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
