"""Real worker/SQLite regressions for multi-request generation."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import DocumentBlock, Notebook, NotebookBlockSource, NotebookGenerationJob
from app.notes.document import load_document, normalize_document
from app.notes.store import write_document
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import make_asset, make_course, make_notebook, persist_ir
from tests.test_generation_limits import _client, _response, _valid_result


@pytest.fixture()
def generation_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'generation.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    from app.services import processing_budget
    monkeypatch.setattr(processing_budget, "SessionLocal", factory)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def _job(db, *, batch_chars=18_000):
    from app.api.v1.generation import create_generation_job
    from app.schemas.generation import NotebookGenerationCreate

    book = make_notebook(db, make_course(db))
    asset = make_asset(db, book)
    persist_ir(db, book, asset, sections=[
        ("第一部分", ["合成正文甲。" * 70]), ("第二部分", ["合成正文乙。" * 70]),
    ])
    write_document(db, book, normalize_document({"type": "doc", "content": [{
        "type": "paragraph", "attrs": {"blockId": "p0"},
        "content": [{"type": "text", "text": "用户自己保存的正文"}],
    }]}), expected_revision=0, origin="autosave")
    db.commit()
    created = create_generation_job(
        book.id, NotebookGenerationCreate(asset_ids=[asset.id]), "synthetic-generation", db,
    )
    job = db.get(NotebookGenerationJob, created["id"])
    job.generator = "deepseek"
    snapshot = json.loads(job.input_snapshot_json)
    snapshot["batch_chars"] = batch_chars
    job.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    db.commit()
    return book, job


def _run(job_id):
    assert worker.claim_next_generation_job() == job_id
    worker.process_generation_job(job_id)


def test_model_ids_reused_across_planner_batches_keep_exact_sources(generation_db, monkeypatch):
    db = generation_db
    book, job = _job(db, batch_chars=600)
    _client(monkeypatch, _valid_result)
    _run(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "completed", job.error_message
    doc = load_document(db.get(Notebook, book.id).document_json).content
    assert len(json.loads(job.knowledge_plan_json)["batches"]) == 2
    rows = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == book.id,
    )))
    source_text = {
        block["block_id"]: block["text"]
        for source in json.loads(job.input_snapshot_json)["sources"]
        for section in source["sections"] for block in section["blocks"]
    }
    mapped = {row.block_id: db.get(DocumentBlock, row.document_block_id).block_id for row in rows}
    assert len(rows) == 4
    assert len(mapped) == 4
    for node in doc["content"][1:]:
        text = node["content"][0]["text"]
        assert source_text[mapped[node["attrs"]["blockId"]]] == text
    assert doc["content"][0]["content"][0]["text"] == "用户自己保存的正文"


def test_uncertain_provider_failure_keeps_append_atomic_and_blocks_paid_retry(generation_db, monkeypatch):
    from app.api.v1.generation import retry_generation_job

    db = generation_db
    book, job = _job(db)
    should_fail = True
    provider_calls = []

    def responder(payload):
        provider_calls.append(1)
        units = json.loads(payload["messages"][1]["content"])["units"]
        blocks = [block for unit in units for block in unit["blocks"]]
        if len(blocks) > 2:
            return _response('{"nodes":[', "length")
        if should_fail and any("乙" in block["text"] for block in blocks):
            raise httpx.ConnectError("synthetic provider unavailable")
        return _valid_result(payload)

    _client(monkeypatch, responder)
    _run(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "failed"
    assert db.get(Notebook, book.id).document_revision == 1
    assert db.scalar(select(NotebookBlockSource)) is None
    failed_call_count = len(provider_calls)
    should_fail = False
    retry_generation_job(book.id, job.id, db)
    _run(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "budget_uncertain"
    assert len(provider_calls) == failed_call_count
    notebook = db.get(Notebook, book.id)
    assert notebook.document_revision == 1
    assert db.scalar(select(NotebookBlockSource)) is None
    assert "用户自己保存的正文" in notebook.document_json


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_math_normalization_failure_runs_one_atomic_format_repair(
    generation_db, monkeypatch, repair_succeeds,
):
    db = generation_db
    book, job = _job(db, batch_chars=600)
    repairs = []

    def responder(payload):
        request = json.loads(payload["messages"][1]["content"])
        if "units" in request:
            result = json.loads(_valid_result(payload)["choices"][0]["message"]["content"])
            result["nodes"][0] = {"type": "blockMath", "attrs": {
                "blockId": "p0", "latex": "x" * 2_001,
            }}
            return _response(json.dumps(result))
        repairs.append(request)
        for node in request["nodes"]:
            if node["type"] == "blockMath":
                node["attrs"]["latex"] = "x^2" if repair_succeeds else ""
        return _response(json.dumps({"nodes": request["nodes"], "sources": request["sources"]}))

    _client(monkeypatch, responder)
    _run(job.id)
    db.expire_all()
    db.refresh(job)
    assert len(repairs) == 1, (job.status, job.error_code, job.error_message)
    notebook = db.get(Notebook, book.id)
    assert "用户自己保存的正文" in notebook.document_json
    rows = list(db.scalars(select(NotebookBlockSource)))
    if repair_succeeds:
        assert job.status == "completed", job.error_message
        assert notebook.document_revision == 2
        assert len(rows) == 4
        assert len({row.block_id for row in rows}) == 4
        worker.process_generation_job(job.id)
        db.expire_all()
        assert db.get(Notebook, book.id).document_revision == 2
    else:
        assert job.status == "failed"
        assert job.error_code == "document_format_repair_failed"
        assert notebook.document_revision == 1
        assert rows == []


def test_remote_math_and_callout_normalization_preserves_block_ids():
    nodes = [{
        "type": "callout", "attrs": {"blockId": "warning-1", "tone": "danger"},
        "content": [{"type": "inlineMath", "text": " x^2 "}],
    }]
    result = worker._normalize_model_blocks(nodes)
    assert result[0]["attrs"] == {"blockId": "warning-1", "tone": "warning", "title": "请核对"}
    assert result[0]["content"][0] == {"type": "paragraph", "content": [{
        "type": "inlineMath", "attrs": {"latex": "x^2"},
    }]}
    assert nodes[0]["attrs"]["tone"] == "danger"


def test_standard_retry_reuses_valid_batches_without_partial_body_write(generation_db, monkeypatch):
    from app.api.v1.generation import retry_generation_job
    from app.generation.composer import CompositionError

    db = generation_db
    book, job = _job(db, batch_chars=600)
    job.generator = 'offline-extractive'
    db.commit()
    original = worker.compose
    calls = []
    fail = True
    def compose(snapshot, plan, batch, **kwargs):
        calls.append(list(batch))
        if fail and len(calls) == 2:
            raise CompositionError('synthetic late batch failure')
        return original(snapshot, plan, batch, **kwargs)
    monkeypatch.setattr(worker, 'compose', compose)
    _run(job.id)
    db.expire_all()
    assert db.get(NotebookGenerationJob, job.id).status == 'failed'
    assert db.get(Notebook, book.id).document_revision == 1
    assert db.scalar(select(NotebookBlockSource)) is None
    fail = False
    retry_generation_job(book.id, job.id, db)
    _run(job.id)
    db.expire_all()
    assert db.get(NotebookGenerationJob, job.id).status == 'completed'
    assert len(calls) == 3, 'The successful first batch must not be regenerated'
    assert calls[1] == calls[2]
    assert db.get(Notebook, book.id).document_revision == 2


def test_cancel_during_first_draft_response_prevents_repair_request(generation_db, monkeypatch):
    from app.db.models import ProviderUsageReservation
    from app.document_processing import config
    from app.generation.planner import build_plan

    db = generation_db
    book, job = _job(db)
    snapshot = json.loads(job.input_snapshot_json)
    snapshot['processing_route'] = 'llm'
    snapshot['provider'] = {'reading_mode': 'hybrid'}
    job.input_snapshot_json = json.dumps(snapshot)
    job.knowledge_plan_json = json.dumps(build_plan(snapshot))
    db.commit()
    calls = []
    def responder(payload):
        calls.append(1)
        with worker.SessionLocal() as other:
            task = other.get(NotebookGenerationJob, job.id)
            task.status = 'cancel_requested'
            other.commit()
        return _response(json.dumps({'blocks': []}))
    client = _client(monkeypatch, responder)
    monkeypatch.setattr(config, 'provider_client', lambda _: client)
    monkeypatch.setattr(worker, 'provider_client', lambda _: client)
    _run(job.id)
    db.expire_all()
    assert db.get(NotebookGenerationJob, job.id).status == 'cancelled'
    assert len(calls) == 1, 'Cancellation must be checked before any draft-repair HTTP request'
    assert len(list(db.scalars(select(ProviderUsageReservation)))) == 1
    assert db.get(Notebook, book.id).document_revision == 1
