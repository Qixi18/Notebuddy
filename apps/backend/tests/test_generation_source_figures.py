import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.v1.generation import create_generation_job
from app.api.v1.notebook import get_asset_content, restore_unbound_revision
from app.core.config import settings
from app.db.models import (
    DocumentBlock,
    NotebookBlockSource,
    NotebookGenerationJob,
    NotebookRevisionAsset,
)
from app.document_processing.ir import BlockIR, FigureData, SourceSpan
from app.document_processing.normalization.sections import build_sections
from app.document_processing.service import persist_existing_ir
from app.generation.figures import _group_overlapping_figures, append_source_figures
from app.notes.document import DocumentValidationError, load_document
from app.notes.store import write_document
from app.schemas.generation import NotebookGenerationCreate
from app.schemas.notebook import NotebookRestoreRequest
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import make_asset, make_notebook, simple_ir

pytest_plugins = ["tests.notebook_fixtures"]


def test_generation_copies_owned_figure_and_preserves_source_and_history(
    session, engine, monkeypatch, tmp_path,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "notebook_generator", "offline-extractive")
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    book = make_notebook(session, None)
    asset = make_asset(session, book)
    source = tmp_path / asset.storage_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf source")
    ir = simple_ir(asset.id, str(uuid.uuid4()))
    figure = BlockIR(block_id="figure-1", page_number=1, order=3, global_order=3,
                     type="figure", text="电路示意图",
                     figure=FigureData(description="电路示意图", image_key="placeholder"),
                     source=SourceSpan(asset_id=asset.id, page_number=1))
    ir.pages[0].blocks.append(figure)
    ir.sections = build_sections(ir, document_title="资料")
    run = persist_existing_ir(session, asset=asset, document=ir).run
    key = f"derived/figures/{asset.id}/{run.id}/figure.png"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    row = session.scalar(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id, DocumentBlock.block_id == figure.block_id,
    ))
    row.figure_json = json.dumps(FigureData(description="电路示意图", image_key=key).to_dict())
    session.commit()
    job = create_generation_job(book.id, NotebookGenerationCreate(asset_ids=[asset.id]),
                                "figure-test", session)
    session.commit()
    assert worker.claim_next_generation_job() == job["id"]
    worker.process_generation_job(job["id"])
    session.expire_all()
    result = session.get(NotebookGenerationJob, job["id"])
    assert result.status == "completed", result.error_message
    content = load_document(session.get(type(book), book.id).document_json).content
    wrappers = [node for node in content["content"] if any(
        child.get("type") == "image" for child in node.get("content", [])
    )]
    assert len(wrappers) == 1
    attrs = wrappers[0]["content"][0]["attrs"]
    assert attrs["src"] == f"/api/v1/assets/{attrs['assetId']}/content"
    link = session.scalar(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == book.id,
        NotebookBlockSource.block_id == wrappers[0]["attrs"]["blockId"],
    ))
    assert link and link.document_block_id == row.id and link.parse_run_id == run.id
    assert session.scalar(select(NotebookRevisionAsset).where(
        NotebookRevisionAsset.notebook_id == book.id,
        NotebookRevisionAsset.asset_id == attrs["assetId"],
    )) is not None
    response = get_asset_content(attrs["assetId"], db=session)
    assert Path(response.path).read_bytes() == buffer.getvalue()
    current_book = session.get(type(book), book.id)
    write_document(session, current_book, {"type": "doc", "content": []},
                   expected_revision=1)
    session.commit()
    session.refresh(link)
    assert link.status == "stale"
    restored = restore_unbound_revision(book.id, 1, NotebookRestoreRequest(expected_revision=2),
                                        db=session)
    assert restored["revision"] == 3
    session.refresh(link)
    assert link.status == "active"
    assert Path(get_asset_content(attrs["assetId"], db=session).path).read_bytes() == buffer.getvalue()


def test_figure_bridge_rejects_other_notebook_and_outside_run_path(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    owner = make_notebook(session, None)
    other = make_notebook(session, None)
    asset = make_asset(session, owner)
    source = tmp_path / asset.storage_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    ir = simple_ir(asset.id, str(uuid.uuid4()))
    figure = BlockIR(block_id="figure-1", page_number=1, order=3, global_order=3,
                     type="figure", text="chart",
                     figure=FigureData(description="chart", image_key="placeholder"),
                     source=SourceSpan(asset_id=asset.id, page_number=1))
    ir.pages[0].blocks.append(figure)
    ir.sections = build_sections(ir)
    run = persist_existing_ir(session, asset=asset, document=ir).run
    snapshot = {"sources": [{"asset_id": asset.id, "parse_run_id": run.id,
                             "ir_fingerprint": run.fingerprint,
                             "sections": [{"blocks": [{"block_id": "figure-1",
                                                         "figure": {"evidence_ref": "figure-1"}}]}]}]}
    plan = {"units": [{"parse_run_id": run.id, "block_ids": ["figure-1"], "intent": "new"}]}
    with pytest.raises(DocumentValidationError, match="不属于"):
        append_source_figures(session, other.id, snapshot, plan, [], {}, [])
    row = session.scalar(select(DocumentBlock).where(DocumentBlock.block_id == "figure-1"))
    row.figure_json = json.dumps({"image_key": f"derived/figures/{asset.id}/{run.id}/../../secret.png"})
    session.flush()
    with pytest.raises(DocumentValidationError, match="不可用"):
        append_source_figures(session, owner.id, snapshot, plan, [], {}, [])


def test_generation_snapshot_rejects_changed_fingerprint_and_detached_owner(session):
    from app.db.models import NotebookAsset
    from app.generation.context import GenerationInputError, build_snapshot

    book = make_notebook(session, None)
    asset = make_asset(session, book)
    ir = simple_ir(asset.id, str(uuid.uuid4()))
    run = persist_existing_ir(session, asset=asset, document=ir).run
    snapshot = build_snapshot(session, book, [asset.id])
    worker._validate_snapshot_sources(session, book.id, snapshot)
    snapshot["sources"][0]["ir_fingerprint"] = "changed"
    with pytest.raises(GenerationInputError, match="失效"):
        worker._validate_snapshot_sources(session, book.id, snapshot)
    snapshot["sources"][0]["ir_fingerprint"] = run.fingerprint
    owner = session.scalar(select(NotebookAsset).where(NotebookAsset.asset_id == asset.id))
    owner.detached_at = datetime.now(UTC)
    session.flush()
    with pytest.raises(GenerationInputError, match="失效"):
        worker._validate_snapshot_sources(session, book.id, snapshot)


def test_only_unambiguous_overlapping_figure_and_original_are_grouped():
    from types import SimpleNamespace

    page = SimpleNamespace(id="page", width=612, height=792, rotation=0)

    def block(name, kind, extraction, bbox):
        return SimpleNamespace(block_id=name, block_type=kind, extraction=extraction,
                               parse_run_id="run", bbox_json=json.dumps(bbox))

    visual = block("visual", "figure", "mineru", [99, 548, 918, 766])
    original = block("original", "image", "native_text", [45, 405, 565, 650])
    unrelated = block("other", "image", "native_text", [20, 20, 200, 150])
    candidates = [(visual, page, {}, Path("v")), (original, page, {}, Path("o")),
                  (unrelated, page, {}, Path("x"))]
    grouped = list(_group_overlapping_figures(candidates))
    assert [(item[0].block_id, refs) for item, refs in grouped] == [
        ("original", ["visual"]), ("other", []),
    ]
    page.rotation = 90
    assert len(list(_group_overlapping_figures(candidates))) == 3
    page.rotation = 0
    additional = block("another-visual", "figure", "mineru", [99, 548, 918, 766])
    assert len(list(_group_overlapping_figures(
        [*candidates, (additional, page, {}, Path("v2"))],
    ))) == 4
