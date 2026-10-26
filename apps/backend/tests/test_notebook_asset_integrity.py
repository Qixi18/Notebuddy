from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    Asset,
    AssetParseResult,
    AssetProcessingJob,
    Notebook,
    NotebookAsset,
    NotebookCoverAsset,
    NotebookDocumentRevision,
    NotebookGenerationCandidate,
    NotebookGenerationJob,
    NotebookRevisionAsset,
    utc_now,
)
from app.notes.history import record_snapshot
from app.services import uploads


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


def _notebook(title: str) -> Notebook:
    return Notebook(title=title, tree_slot=0, document_json='{"type":"doc","content":[]}')


def _asset(*, source_type: str = "user_upload") -> Asset:
    now = utc_now()
    return Asset(
        source_type=source_type,
        media_type="image",
        mime_type="image/svg+xml" if source_type == "ai_render" else "image/png",
        extension=".svg" if source_type == "ai_render" else ".png",
        original_name="diagram.svg" if source_type == "ai_render" else "source.png",
        storage_key=f"assets/{source_type}/stable-id",
        byte_size=1,
        sha256="a" * 64,
        state="ready",
        created_at=now,
        verified_at=now,
    )


def test_asset_can_have_only_one_active_notebook_owner_and_can_be_reowned(db):
    first, second = _notebook("第一篇"), _notebook("第二篇")
    asset = _asset(source_type="ai_render")
    db.add_all([first, second, asset])
    db.flush()
    old_owner = NotebookAsset(
        notebook_id=first.id, asset_id=asset.id, role="inline_image", is_owner=True,
    )
    db.add(old_owner)
    db.commit()

    db.add(NotebookAsset(
        notebook_id=second.id, asset_id=asset.id, role="source_material", is_owner=True,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    old_owner.detached_at = utc_now()
    db.commit()
    new_owner = NotebookAsset(
        notebook_id=second.id, asset_id=asset.id, role="inline_image", is_owner=True,
    )
    db.add(new_owner)
    db.commit()
    assert old_owner.detached_at is not None
    assert new_owner.is_owner is True
    assert asset.source_type == "ai_render"  # Origin and Notebook use are independent.


def test_revision_asset_composite_fk_rejects_cross_notebook_owner(db):
    first, second = _notebook("正文归属"), _notebook("错误归属")
    asset = _asset()
    db.add_all([first, second, asset])
    db.flush()
    owner = NotebookAsset(
        notebook_id=second.id, asset_id=asset.id, role="inline_image", is_owner=True,
    )
    revision = NotebookDocumentRevision(
        notebook_id=first.id, revision=1, schema_version=2,
        document_json='{"type":"doc","content":[]}', origin="autosave",
    )
    db.add_all([owner, revision])
    db.flush()
    db.add(NotebookRevisionAsset(
        revision_id=revision.id, notebook_id=first.id,
        owner_link_id=owner.id, asset_id=asset.id,
    ))
    with pytest.raises(IntegrityError):
        db.commit()


def test_asset_jobs_covers_and_candidates_cannot_cross_notebook_owners(db):
    first, second = _notebook("归属笔记"), _notebook("其他笔记")
    asset = _asset()
    db.add_all([first, second, asset])
    db.flush()
    owner = NotebookAsset(
        notebook_id=second.id, asset_id=asset.id, role="source_material", is_owner=True,
    )
    generation = NotebookGenerationJob(
        notebook_id=first.id, idempotency_key="key", request_fingerprint="f" * 64,
        status="candidate_ready", base_document_revision=0, input_snapshot_json="{}",
        model="test", prompt_version="test", schema_version=2, attempt_count=1,
    )
    db.add_all([owner, generation])
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(AssetProcessingJob(
            asset_id=asset.id, notebook_id=first.id, owner_link_id=owner.id,
            kind="image_parse", status="pending", attempt_count=0,
        ))
        db.commit()
    db.rollback()

    # A candidate and its registered cover pointer must name the same Notebook
    # as their parent job/owner link at the database boundary.
    with pytest.raises(IntegrityError):
        db.add(NotebookGenerationCandidate(
            job_id=generation.id, notebook_id=second.id,
            document_json='{"type":"doc","content":[]}', status="pending_review",
        ))
        db.commit()
    db.rollback()

    with pytest.raises(IntegrityError):
        db.add(NotebookCoverAsset(
            notebook_id=first.id, asset_id=asset.id, owner_link_id=owner.id,
        ))
        db.commit()


def test_document_upload_keeps_staging_state_until_atomic_finalize(db, monkeypatch, tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = BytesIO()
    writer.write(pdf)
    data = pdf.getvalue()
    notebook = _notebook("光的干涉")
    db.add(notebook)
    db.commit()

    data_dir = tmp_path / "data"
    monkeypatch.setattr(uploads, "settings", SimpleNamespace(
        data_dir=data_dir,
        originals_dir=data_dir / "originals",
        allowed_extensions={".pdf"},
        max_upload_bytes=1_000_000,
        max_pages=20,
    ))
    original_replace = uploads.os.replace
    fail_final_promotion = True

    def fail_once(source, destination):
        nonlocal fail_final_promotion
        if fail_final_promotion and Path(destination).parent == data_dir / "originals":
            fail_final_promotion = False
            raise OSError("simulated transient rename failure")
        return original_replace(source, destination)

    monkeypatch.setattr(uploads.os, "replace", fail_once)
    material, job = uploads.ingest_document(
        db,
        course_id=None,
        notebook_id=notebook.id,
        source=BytesIO(data),
        filename="光学.pdf",
        lecture_title="光学",
        topic_title="",
        media_type="text/plain",  # Must not override the verified PDF MIME.
    )
    asset = db.get(Asset, material.asset_id)
    assert material.notebook_id == notebook.id
    assert material.course_id is None
    assert asset.mime_type == "application/pdf"
    assert asset.state == "staging"
    assert (data_dir / "staging" / f"{asset.id}.upload").is_file()
    assert job.status == "pending"

    monkeypatch.setattr(uploads.os, "replace", original_replace)
    assert uploads.reconcile_staged_document_assets(db) == 1
    db.refresh(asset)
    assert asset.state == "ready"
    final_path = data_dir / asset.storage_key
    assert final_path.is_file()
    assert hashlib.sha256(final_path.read_bytes()).hexdigest() == asset.sha256
    assert db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset.id,
        NotebookAsset.notebook_id == notebook.id,
        NotebookAsset.is_owner.is_(True),
    )) is not None


def test_record_snapshot_pins_detached_owner_for_historical_restore(db):
    notebook = _notebook("历史图片")
    asset = _asset()
    db.add_all([notebook, asset])
    db.flush()
    owner = NotebookAsset(
        notebook_id=notebook.id, asset_id=asset.id, role="inline_image", is_owner=True,
        detached_at=utc_now(),
    )
    db.add(owner)
    db.flush()
    snapshot = record_snapshot(db, notebook.id, 1, {
        "type": "doc",
        "content": [{"type": "image", "attrs": {"assetId": asset.id}}],
    })
    db.commit()
    pin = db.query(NotebookRevisionAsset).filter_by(revision_id=snapshot.id).one()
    assert pin.owner_link_id == owner.id


def test_original_image_is_parsed_and_used_in_reviewable_generation(db, monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.api.v1.generation import apply_generation_candidate, create_generation_job
    from app.notes import assets as asset_store
    from app.schemas.generation import NotebookGenerationApply, NotebookGenerationCreate
    from app.services import image_assets
    from app.workers import asset_worker, notebook_generation_worker

    engine = db.get_bind()
    session_factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(image_assets, "settings", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(asset_store, "settings", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(asset_worker, "SessionLocal", session_factory)
    monkeypatch.setattr(notebook_generation_worker, "SessionLocal", session_factory)

    notebook = _notebook("原始图片解析")
    db.add(notebook)
    db.commit()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
        "pJkAAAAASUVORK5CYII="
    )
    asset, parse_job = image_assets.ingest_source_image(
        db, notebook_id=notebook.id, filename="作业.png", data=png,
    )
    assert asset.state == "ready" and parse_job is not None
    assert parse_job.status == "pending"
    assert asset_worker.claim_next_asset_job() == parse_job.id
    monkeypatch.setattr(asset_worker, "ocr_image", lambda *_args, **_kwargs: (
        "光程差 Δ=2d cosθ", "test-ocr", 0.98,
    ))
    asset_worker.process_asset_job(parse_job.id)
    parsed = db.scalar(select(AssetParseResult).where(AssetParseResult.asset_id == asset.id))
    assert parsed is not None and '"text": "光程差 Δ=2d cosθ"' in parsed.result_json

    generated = create_generation_job(
        notebook.id, NotebookGenerationCreate(), None, db,
    )
    snapshot = json.loads(db.get(NotebookGenerationJob, generated["id"]).input_snapshot_json)
    assert snapshot["sources"][0]["asset_id"] == asset.id
    assert snapshot["sources"][0]["text"] == "光程差 Δ=2d cosθ"

    class FakeDeepSeek:
        def complete_json(self, *_args, **_kwargs):
            return {"type": "doc", "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [
                    {"type": "text", "text": "光程差"},
                ]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Δ=2d cosθ"},
                ]},
            ]}

    monkeypatch.setattr(notebook_generation_worker, "DeepSeekClient", FakeDeepSeek)
    assert notebook_generation_worker.claim_next_generation_job() == generated["id"]
    notebook_generation_worker.process_generation_job(generated["id"])
    job = db.get(NotebookGenerationJob, generated["id"])
    assert job.status == "candidate_ready"
    applied = apply_generation_candidate(
        notebook.id, job.id, NotebookGenerationApply(expected_revision=0), db,
    )
    db.refresh(notebook)
    assert applied["status"] == "applied"
    assert notebook.document_revision == 1
    assert db.scalar(select(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == notebook.id,
        NotebookDocumentRevision.revision == 1,
    )) is not None
