"""End-to-end Notebook generation from Document IR (offline composer)."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import (
    Notebook,
    NotebookBlockSource,
    NotebookGenerationJob,
    NotebookSection,
)
from app.generation.composer import CompositionError, compose_deepseek
from app.notes.document import load_document
from app.schemas.generation import NotebookGenerationCreate
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_notebook,
    persist_ir,
)


def test_model_table_cells_and_callout_inline_content_are_normalized():
    from app.notes.document import normalize_document, validate_document

    nodes = [{"type": "table", "attrs": {"blockId": "table"}, "content": [
        {"type": "tableRow", "content": [
            {"type": "tableHeader", "content": [{"type": "text", "text": "A"}]},
            {"type": "tableCell", "content": [{"type": "text", "text": "1"}]},
        ]},
    ]}, {"type": "callout", "attrs": {"blockId": "warning", "tone": "warning"},
         "content": [{"type": "text", "text": "需要核对"}]}]
    repaired = worker._normalize_model_blocks(nodes)
    validate_document(normalize_document({"type": "doc", "content": repaired}))
    assert repaired[0]["content"][0]["content"][0]["content"][0]["type"] == "paragraph"
    assert repaired[1]["attrs"]["title"] == "请核对"
    assert nodes[0]["content"][0]["content"][0]["content"][0]["type"] == "text"


@pytest.fixture()
def file_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(file_db):
    with Session(file_db, autoflush=False, expire_on_commit=False) as session:
        yield session


def _setup(db, *, sections=None):
    course = make_course(db)
    book = make_notebook(db, course)
    asset = make_asset(db, book)
    persist_ir(db, book, asset, sections=sections)
    db.commit()
    return course, book, asset


def _create_job(db, book, asset, key: str = "job-key-1"):
    from app.api.v1.generation import create_generation_job

    return create_generation_job(
        book.id, NotebookGenerationCreate(asset_ids=[asset.id]), key, db,
    )


def _run_worker(monkeypatch, file_db, job_id: str):
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(
        bind=file_db, autoflush=False, expire_on_commit=False))
    claimed = worker.claim_next_generation_job()
    assert claimed == job_id
    worker.process_generation_job(claimed)


def test_offline_generation_appends_document_with_sources(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    assert created["status"] == "pending"
    assert created["generator"] == "offline-extractive"

    _run_worker(monkeypatch, file_db, created["id"])

    db.expire_all()
    job = db.get(NotebookGenerationJob, created["id"])
    notebook = db.get(Notebook, book.id)
    assert job.status == "completed", job.error_message
    assert notebook.document_revision == 1
    content = load_document(notebook.document_json).content
    headings = [node for node in content["content"] if node.get("type") == "heading"]
    assert any("极限" in "".join(
        child.get("text", "") for child in node.get("content") or []) for node in headings)
    assert len(content["content"]) >= 2
    sources = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == book.id)).all())
    assert sources
    assert all(source.parse_run_id for source in sources)
    sections = list(db.scalars(select(NotebookSection).where(
        NotebookSection.notebook_id == book.id)).all())
    assert sections
    assert notebook.document_json.count('"type":"image"') == 0


def test_generation_rejects_insufficient_parse_quality(db):
    course = make_course(db)
    book = make_notebook(db, course)
    asset = make_asset(db, book)
    # A failed run with no usable text.
    from app.document_processing.service import persist_existing_ir
    from tests.notebook_fixtures import simple_ir

    document = simple_ir(asset.id, "run-empty", sections=[("空", ["短"])])
    for block in document.pages[0].blocks:
        block.text = ""
    document.pages[0].text = ""
    persist_existing_ir(db, asset=asset, document=document)
    db.commit()
    with pytest.raises(HTTPException) as captured:
        _create_job(db, book, asset, "bad-quality")
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "parse_quality_insufficient"


def test_generation_is_idempotent_and_does_not_duplicate(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    first = _create_job(db, book, asset, "same-key")
    second = _create_job(db, book, asset, "same-key")
    assert first["id"] == second["id"]
    _run_worker(monkeypatch, file_db, first["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    first_revision = notebook.document_revision
    nodes_before = len(load_document(notebook.document_json).content["content"])
    # Re-running a completed job is a no-op (status guard).
    worker.process_generation_job(first["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    assert notebook.document_revision == first_revision
    assert len(load_document(notebook.document_json).content["content"]) == nodes_before


def test_user_edit_during_generation_is_preserved(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    created = _create_job(db, book, asset, "conflict-key")
    # User saves while the job is pending.
    from app.notes.document import normalize_document
    from app.notes.store import write_document

    user_content = normalize_document({
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockId": "user-1"},
             "content": [{"type": "text", "text": "用户自己的笔记内容"}]},
        ],
    })
    write_document(db, db.get(Notebook, book.id), user_content,
                   expected_revision=0, origin="autosave")
    db.commit()

    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    texts = json.dumps(load_document(notebook.document_json).content, ensure_ascii=False)
    assert "用户自己的笔记内容" in texts
    assert "极限" in texts
    assert notebook.document_revision >= 2


def test_incremental_generation_only_adds_new_sections(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    created = _create_job(db, book, asset, "first")
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    before = load_document(notebook.document_json).content["content"]
    assert any("第一章" in json.dumps(node, ensure_ascii=False) for node in before)

    # A second asset with the same first section and a new second section.
    asset2 = make_asset(db, book, name="资料2.pdf")
    persist_ir(db, book, asset2, sections=[
        ("第一章 极限", ["重复的极限内容。" * 40]),
        ("第二章 连续", ["连续性的定义：函数在一点连续当且仅当极限等于函数值。" * 20]),
    ])
    db.commit()
    job2 = _create_job(db, book, asset2, "second")
    _run_worker(monkeypatch, file_db, job2["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    after = load_document(notebook.document_json).content["content"]
    assert len(after) > len(before)
    combined = json.dumps(after, ensure_ascii=False)
    assert combined.count("第一章 极限") == 1
    assert combined.count("第二章 连续") == 1


def test_every_generated_block_has_a_source_link(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    created = _create_job(db, book, asset, "sources")
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    content = load_document(notebook.document_json).content
    linked = {row.block_id for row in db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == book.id)).all()}
    generated = [
        (node.get("attrs") or {}).get("blockId") for node in content["content"]
        if (node.get("attrs") or {}).get("blockId", "").startswith("ai-")
    ]
    assert generated
    assert set(generated).issubset(linked)


def test_deepseek_output_without_sources_is_rejected():
    from app.generation.context import build_snapshot  # noqa: F401 - contract import
    from app.generation.planner import build_plan
    from tests.notebook_fixtures import simple_ir

    document = simple_ir("asset-1", "run-12345678")
    document.seal()
    snapshot = {
        "notebook_title": "测试",
        "current_outline": [],
        "sources": [{
            "asset_id": "asset-1", "name": "资料", "parse_run_id": "run-12345678",
            "sections": [{
                "section_id": "sec-1", "title": "第一章",
                "blocks": [{"block_id": "b1", "type": "paragraph", "text": "内容"}],
            }],
        }],
        "batch_chars": 18000,
    }
    plan = build_plan(snapshot)

    class FakeClient:
        configured = True

        def complete_json(self, *_args, **_kwargs):
            return {"nodes": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}]}

    from app.generation import composer

    original = composer.DeepSeekClient
    composer.DeepSeekClient = lambda: FakeClient()
    try:
        with pytest.raises(CompositionError) as captured:
            compose_deepseek(snapshot, plan, [plan["units"][0]["unit_id"]])
        assert captured.value.code == "missing_sources"
    finally:
        composer.DeepSeekClient = original


def _link_input(db, book, asset, job_id):
    from app.db.model_utils import new_id
    from app.db.models import NotebookGenerationInput, NotebookUploadBatch

    batch = NotebookUploadBatch(id=new_id(), notebook_id=book.id)
    db.add(batch)
    db.flush()
    row = NotebookGenerationInput(
        id=new_id(), notebook_id=book.id, asset_id=asset.id, batch_id=batch.id,
        parse_kind="material", status="generating", generation_job_id=job_id,
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("provider_fails", [False, True])
def test_cancel_during_provider_call_never_writes_body_or_sources(
    db, file_db, monkeypatch, provider_fails,
):
    from app.api.v1.generation import cancel_generation_job
    from app.db.models import NotebookDocumentRevision, NotebookGenerationInput

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    input_row = _link_input(db, book, asset, created["id"])
    original_compose = worker.compose

    def cancelling_compose(*args, **kwargs):
        with Session(file_db) as request_db:
            response = cancel_generation_job(book.id, created["id"], request_db)
            assert response["status"] == "cancel_requested"
        if provider_fails:
            raise CompositionError("provider failed after cancellation")
        return original_compose(*args, **kwargs)

    monkeypatch.setattr(worker, "compose", cancelling_compose)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(NotebookGenerationJob, created["id"]).status == "cancelled"
    assert db.get(Notebook, book.id).document_revision == 0
    assert db.scalar(select(NotebookDocumentRevision)) is None
    assert db.scalar(select(NotebookBlockSource)) is None
    assert db.get(NotebookGenerationInput, input_row.id).error_code == "cancelled"


def test_pending_cancel_updates_input_and_can_retry(db, file_db, monkeypatch):
    from app.api.v1.generation import cancel_generation_job, retry_generation_job
    from app.db.models import NotebookGenerationInput

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    row = _link_input(db, book, asset, created["id"])
    response = cancel_generation_job(book.id, created["id"], db)
    assert response["status"] == "cancelled"
    db.refresh(row)
    assert row.status == "generation_failed"
    response = retry_generation_job(book.id, created["id"], db)
    assert response["status"] == "pending"
    db.refresh(row)
    assert row.status == "generating"
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(NotebookGenerationInput, row.id).status == "completed"


def test_second_delivery_of_processing_job_cannot_append_twice(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    original_compose = worker.compose
    delivered = False

    def redelivering_compose(*args, **kwargs):
        nonlocal delivered
        if not delivered:
            delivered = True
            worker.process_generation_job(created["id"])
        return original_compose(*args, **kwargs)

    monkeypatch.setattr(worker, "compose", redelivering_compose)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(Notebook, book.id).document_revision == 1
    assert db.get(NotebookGenerationJob, created["id"]).status == "completed"


def test_old_attempt_result_is_discarded_after_cancel_and_retry(db, file_db, monkeypatch):
    from app.api.v1.generation import cancel_generation_job, retry_generation_job

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    original_compose = worker.compose
    restarted = False

    def retrying_compose(*args, **kwargs):
        nonlocal restarted
        if not restarted:
            restarted = True
            with Session(file_db) as request_db:
                cancel_generation_job(book.id, created["id"], request_db)
            worker.process_generation_job(created["id"])  # acknowledge cancellation
            with Session(file_db) as request_db:
                retried = retry_generation_job(book.id, created["id"], request_db)
                assert retried["attempt_count"] == 1
            assert worker.claim_next_generation_job() == created["id"]
            worker.process_generation_job(created["id"])
        return original_compose(*args, **kwargs)

    monkeypatch.setattr(worker, "compose", retrying_compose)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(Notebook, book.id).document_revision == 1
    assert db.get(NotebookGenerationJob, created["id"]).attempt_count == 2


def test_concurrent_claims_serialize_one_notebook(db, file_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, book, asset = _setup(db)
    first = _create_job(db, book, asset, "first")
    second = _create_job(db, book, asset, "second")
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=file_db))
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        return worker.claim_next_generation_job()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert sum(item is not None for item in claims) == 1
    with Session(file_db) as request_db:
        running = list(request_db.scalars(select(NotebookGenerationJob).where(
            NotebookGenerationJob.status == "processing",
        )))
        assert len(running) == 1
        running_id = running[0].id
        running[0].status = "cancel_requested"
        request_db.commit()
    assert worker.claim_next_generation_job() is None
    worker.process_generation_job(running_id)
    assert worker.claim_next_generation_job() in {first["id"], second["id"]} - set(claims)


def test_unmapped_generated_block_is_rejected_before_commit(db, file_db, monkeypatch):
    from app.generation.composer import Composition, paragraph

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    monkeypatch.setattr(worker, "compose", lambda *args, **kwargs: Composition(
        nodes=[paragraph("没有来源的生成内容")], source_map={},
    ))
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    task = db.get(NotebookGenerationJob, created["id"])
    assert task.status == "failed"
    assert task.error_code == "document_validation_failed"
    assert db.get(Notebook, book.id).document_revision == 0


def test_source_write_failure_rolls_back_entire_append(db, file_db, monkeypatch):
    from app.db.models import NotebookDocumentRevision

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)

    def fail_sources(*args, **kwargs):
        raise RuntimeError("simulated interruption before provenance commit")

    monkeypatch.setattr(worker, "_write_sources", fail_sources)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(Notebook, book.id).document_revision == 0
    assert db.scalar(select(NotebookDocumentRevision)) is None
    assert db.scalar(select(NotebookBlockSource)) is None


def test_cancel_requested_job_is_reconciled_after_runner_restart(db, file_db, monkeypatch):
    from app.db.models import NotebookGenerationInput
    from app.workers import runner

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    row = _link_input(db, book, asset, created["id"])
    task = db.get(NotebookGenerationJob, created["id"])
    task.status = "cancel_requested"
    db.commit()
    monkeypatch.setattr(runner, "SessionLocal", sessionmaker(bind=file_db))
    runner.mark_interrupted_jobs(force=True)
    db.expire_all()
    assert db.get(NotebookGenerationJob, task.id).status == "cancelled"
    assert db.get(NotebookGenerationInput, row.id).status == "generation_failed"


def test_sources_are_stale_after_rewrite_and_active_after_exact_restore(db, file_db, monkeypatch):
    from copy import deepcopy

    from app.notes.store import write_document

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    generated = load_document(notebook.document_json).content
    edited = deepcopy(generated)
    paragraph = next(node for node in edited["content"] if node["type"] == "paragraph")
    block_id = paragraph["attrs"]["blockId"]
    paragraph["content"] = [{"type": "text", "text": "用户改写后已无法确认原始证据是否支持这段内容"}]
    write_document(db, notebook, edited, expected_revision=1, origin="autosave")
    db.commit()
    db.expire_all()
    links = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.block_id == block_id,
    )))
    assert links and all(link.body_fingerprint for link in links)
    assert all(link.status == "stale" for link in links)
    write_document(db, notebook, generated, expected_revision=2, origin="restore")
    db.commit()
    db.expire_all()
    assert all(link.status == "active" for link in links)
    assert notebook.document_revision == 3


def test_legacy_active_source_is_not_rebound_to_edited_text(db, file_db, monkeypatch):
    from app.notes.store import write_document

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    content = load_document(notebook.document_json).content
    original = json.loads(json.dumps(content))
    node = next(node for node in content["content"] if node["type"] == "paragraph")
    links = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.block_id == node["attrs"]["blockId"],
    )))
    for link in links:
        link.body_fingerprint = None  # simulate rows created before this migration
    db.commit()
    node["content"] = [{"type": "text", "text": "改成与资料不同的论断"}]
    write_document(db, notebook, content, expected_revision=1)
    db.commit()
    db.expire_all()
    assert all(link.status == "stale" for link in links)
    write_document(db, notebook, original, expected_revision=2, origin="restore")
    db.commit()
    db.expire_all()
    assert all(link.status == "active" for link in links)


def test_queued_jobs_with_different_keys_do_not_repeat_same_parse(db, file_db, monkeypatch):
    _, book, asset = _setup(db)
    first = _create_job(db, book, asset, "first")
    second = _create_job(db, book, asset, "second")
    _run_worker(monkeypatch, file_db, first["id"])
    _run_worker(monkeypatch, file_db, second["id"])
    db.expire_all()
    assert db.get(Notebook, book.id).document_revision == 1
    repeated = db.get(NotebookGenerationJob, second["id"])
    assert repeated.status == "completed"
    plan = json.loads(repeated.knowledge_plan_json)
    assert plan["skip_count"] > 0
    assert plan["batches"] == []


def test_history_restore_then_upload_only_generates_new_source(db, file_db, monkeypatch):
    from app.api.v1.generation import create_generation_job
    from app.notes.store import write_document

    _, book, asset = _setup(db)
    first = _create_job(db, book, asset)
    _run_worker(monkeypatch, file_db, first["id"])
    db.expire_all()
    notebook = db.get(Notebook, book.id)
    # Restore the initial empty version; the old input remains consumed.
    write_document(db, notebook, {"type": "doc", "content": []},
                   expected_revision=1, origin="restore")
    new_asset = make_asset(db, book, name="新资料.pdf")
    persist_ir(db, book, new_asset, sections=[("第二章 连续", ["连续性的完整定义和推导。" * 40])])
    db.commit()
    created = create_generation_job(
        book.id, NotebookGenerationCreate(asset_ids=[asset.id, new_asset.id]), "new-upload", db,
    )
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    text = json.dumps(load_document(notebook.document_json).content, ensure_ascii=False)
    assert "第二章 连续" in text
    assert "第一章 极限" not in text
    assert notebook.document_revision == 3


def test_cancel_after_composition_before_atomic_write(db, file_db, monkeypatch):
    from app.api.v1.generation import cancel_generation_job

    _, book, asset = _setup(db)
    created = _create_job(db, book, asset)
    original = worker._resolve_source_rows

    def cancelling_resolve(*args, **kwargs):
        rows = original(*args, **kwargs)
        with Session(file_db) as request_db:
            cancel_generation_job(book.id, created["id"], request_db)
        return rows

    monkeypatch.setattr(worker, "_resolve_source_rows", cancelling_resolve)
    _run_worker(monkeypatch, file_db, created["id"])
    db.expire_all()
    assert db.get(NotebookGenerationJob, created["id"]).status == "cancelled"
    assert db.get(Notebook, book.id).document_revision == 0
