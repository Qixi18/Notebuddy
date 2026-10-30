"""Reproductions for independently reviewed large-document failure modes."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.core.config import settings
from app.db.models import ForestJob, NotebookGenerationInput, NotebookGenerationJob
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_notebook,
    make_sessionmaker,
    persist_ir,
)

pytest_plugins = ['tests.notebook_fixtures']


def test_composition_namespaces_same_ids_across_batches(session):
    from app.generation.composer import Composition
    from app.generation.resume import compose_batch
    from app.notes.document import validate_document
    snapshot = {'sources': [{'sections': [{'blocks': [{'block_id': 'e1'}]}]}]}
    def provider(*args, **kwargs):
        return Composition(nodes=[{'type': 'paragraph', 'attrs': {'blockId': 'p1'},
            'content': [{'type': 'text', 'text': 'Grounded content'}]}], source_map={'p1': ['e1']})
    first = compose_batch(session, 'job', snapshot, {}, ['u1'], 'deepseek', compose_impl=provider)
    second = compose_batch(session, 'job', snapshot, {}, ['u2'], 'deepseek', compose_impl=provider)
    ids = [item.nodes[0]['attrs']['blockId'] for item in (first, second)]
    assert len(set(ids)) == 2
    validate_document({'type': 'doc', 'content': first.nodes + second.nodes})
    assert set(first.source_map) | set(second.source_map) == set(ids)


def test_changed_route_in_same_batch_generates_separate_jobs(session):
    from app.services.notebook_generation_inputs import (
        coordinate_generation_inputs,
        ensure_upload_batch,
        register_generation_input,
    )
    book = make_notebook(session, make_course(session))
    batch = ensure_upload_batch(session, book.id, None, close_if_new=True, processing_route='standard')
    for route in ('standard', 'llm'):
        asset = make_asset(session, book, name=f'{route}.pdf')
        asset.processing_route = route
        persist_ir(session, book, asset)
        register_generation_input(session, notebook_id=book.id, asset_id=asset.id, batch_id=batch.id,
                                  parse_kind='material', parse_job_id=None)
    session.commit()
    assert coordinate_generation_inputs(session) == 2
    jobs = list(session.scalars(select(NotebookGenerationJob)))
    assert {json.loads(job.input_snapshot_json)['processing_route'] for job in jobs} == {'standard', 'llm'}
    assert {row.status for row in session.scalars(select(NotebookGenerationInput))} == {'generating'}


def test_resuming_six_pages_renders_each_page_only_once(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing import llm_reader, service
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    book = make_notebook(session, make_course(session))
    asset = make_asset(session, book)
    asset.processing_route = 'llm'
    path = tmp_path / 'six.pdf'
    pdf = PdfWriter()
    for _ in range(6):
        pdf.add_blank_page(width=100, height=100)
    pdf.write(path)
    session.commit()
    rendered = []
    real_images = llm_reader.page_images
    @contextmanager
    def tracked(*args):
        with real_images(*args) as (count, render):
            def draw(number):
                rendered.append(number)
                return render(number)
            yield count, draw
    monkeypatch.setattr(llm_reader, 'page_images', tracked)
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k:
        {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'A useful page of source evidence.'}]})
    run = service.create_parse_run(session, asset=asset)
    for tick in range(3):
        if tick < 2:
            with pytest.raises(llm_reader.ReadingPending):
                service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
        else:
            service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
    assert rendered == [1, 2, 3, 4, 5, 6]


def test_long_relation_summary_fits_final_envelope():
    from app.forest.llm_relations import propose_relations
    snapshot = {'sources': [{'key': 's0', 'excerpt': 'x' * 48000}],
                'targets': [{'key': 't0', 'excerpt': 'A target concept.'}]}
    def provider(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        return {'summary': 's' * 900} if isinstance(payload, list) else {'relations': []}
    assert propose_relations(snapshot, provider) == []


def _generation(book, created, updated, key):
    return NotebookGenerationJob(notebook_id=book.id, idempotency_key=key,
        request_fingerprint=key, status='pending', base_document_revision=0,
        input_snapshot_json='{}', model='test', prompt_version='test',
        created_at=created, updated_at=updated)


def test_yielding_generation_lets_another_notebook_run(session, engine, monkeypatch):
    from app.workers import notebook_generation_worker as worker
    now = datetime.now(UTC)
    book1 = make_notebook(session, make_course(session))
    book2 = make_notebook(session, make_course(session))
    first = _generation(book1, now - timedelta(seconds=2), now, 'a')
    second = _generation(book2, now - timedelta(seconds=1), now - timedelta(seconds=1), 'b')
    session.add_all([first, second]); session.commit()
    monkeypatch.setattr(worker, 'SessionLocal', make_sessionmaker(engine))
    assert worker.claim_next_generation_job() == second.id


def test_yielding_forest_job_lets_another_course_run(session, engine, monkeypatch):
    from app.forest import jobs
    now = datetime.now(UTC)
    first = ForestJob(kind='notebook_relations', status='pending', created_at=now-timedelta(seconds=2), updated_at=now)
    second = ForestJob(kind='notebook_relations', status='pending', created_at=now-timedelta(seconds=1), updated_at=now-timedelta(seconds=1))
    session.add_all([first, second]); session.commit()
    monkeypatch.setattr(jobs, 'SessionLocal', make_sessionmaker(engine))
    assert jobs.claim_next_forest_job() == second.id


def test_yielding_generation_preserves_order_inside_one_notebook(session, engine, monkeypatch):
    from app.workers import notebook_generation_worker as worker
    now = datetime.now(UTC)
    book = make_notebook(session, make_course(session))
    first = _generation(book, now - timedelta(seconds=2), now, 'first')
    second = _generation(book, now - timedelta(seconds=1), now - timedelta(seconds=1), 'second')
    session.add_all([first, second])
    session.commit()
    monkeypatch.setattr(worker, 'SessionLocal', make_sessionmaker(engine))
    assert worker.claim_next_generation_job() == first.id


def test_office_timeout_cleans_only_recorded_owned_process(tmp_path, monkeypatch):
    import subprocess

    from app.document_processing import rendering
    source = tmp_path / 'sample.docx'
    source.write_bytes(b'synthetic container')
    monkeypatch.setattr(rendering, 'office_converter', lambda: 'windows-office')
    cleaned = []
    def run(command, **kwargs):
        if 'cleanup_office.ps1' in ' '.join(command):
            cleaned.append(command)
            return subprocess.CompletedProcess(command, 0)
        raise subprocess.TimeoutExpired(command, 120)
    monkeypatch.setattr(rendering.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='超时'):
        rendering.convert_office(source, tmp_path / 'out')
    assert len(cleaned) == 1
    assert '-OwnerProcessFile' in cleaned[0]
