"""Route selection is durable and controls admission, never running jobs."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.core import settings_store
from app.core.config import settings
from app.main import app


def test_settings_switch_persists_and_survives_reload(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('# local settings\n', encoding='utf-8')
    monkeypatch.setattr(settings_store, 'ENV_PATH', env)
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(settings, 'document_processing_route', 'standard', raising=False)
    monkeypatch.delenv('NOTEBOOK_SETTINGS_TOKEN', raising=False)
    with TestClient(app) as client:
        response = client.patch('/api/v1/settings', json={'NOTEBOOK_DOCUMENT_PROCESSING_ROUTE': 'llm'})
        assert response.status_code == 200, response.text
        assert response.json()['status']['storage']['processing_route'] == 'llm'
        assert 'NOTEBOOK_DOCUMENT_PROCESSING_ROUTE=llm' in env.read_text(encoding='utf-8')
        assert client.get('/api/v1/config/capabilities').json()['default_processing_route'] == 'llm'
        response = client.patch('/api/v1/settings', json={'NOTEBOOK_DOCUMENT_PROCESSING_ROUTE': 'standard'})
        assert response.status_code == 200
        assert response.json()['status']['storage']['processing_route'] == 'standard'


def test_invalid_route_is_rejected_before_settings_write():
    with pytest.raises(settings_store.SettingsWriteError):
        settings_store._sanitize('NOTEBOOK_DOCUMENT_PROCESSING_ROUTE', 'unknown')


def test_llm_upload_bypasses_standard_docx_position_limit(session, tmp_path, monkeypatch):
    from docx import Document

    from app.services.uploads import ingest_document
    from tests.notebook_fixtures import make_course, make_notebook

    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(settings, 'max_pages', 1)
    course = make_course(session)
    book = make_notebook(session, course)
    document = Document()
    for number in range(4):
        document.add_paragraph(f'Paragraph {number}')
    source = io.BytesIO()
    document.save(source)
    source.seek(0)
    material, job = ingest_document(session, course_id=course.id, notebook_id=book.id,
        source=source, filename='large.docx', lecture_title='test', topic_title='',
        media_type=None, processing_route='llm')
    session.refresh(material)
    assert material.processing_route == 'llm'
    from app.db.models import Asset
    asset = session.get(Asset, material.asset_id)
    assert asset.processing_route == 'llm'
    monkeypatch.setattr(settings, 'document_processing_route', 'standard', raising=False)
    session.expire_all()
    assert session.get(Asset, asset.id).processing_route == 'llm'
    assert job.status == 'pending'


pytest_plugins = ['tests.notebook_fixtures']


def test_batch_freezes_route_when_settings_changes(session, monkeypatch):
    from fastapi import HTTPException

    from app.services.notebook_generation_inputs import ensure_upload_batch
    from tests.notebook_fixtures import make_course, make_notebook
    book = make_notebook(session, make_course(session))
    monkeypatch.setattr(settings, 'document_processing_route', 'llm')
    batch = ensure_upload_batch(session, book.id, 'batch-freeze')
    monkeypatch.setattr(settings, 'document_processing_route', 'standard')
    assert ensure_upload_batch(session, book.id, batch.id).processing_route == 'llm'
    with pytest.raises(HTTPException) as error:
        ensure_upload_batch(session, book.id, batch.id, processing_route='standard')
    assert error.value.status_code == 409


def test_switching_failed_asset_keeps_old_parse_and_requeues_same_source(session, monkeypatch):
    from app.api.v1.materials import ProcessingRouteSelection, switch_asset_processing_route
    from app.document_processing.service import current_run
    from tests.notebook_fixtures import (
        make_asset,
        make_course,
        make_material,
        make_notebook,
        persist_ir,
    )
    book = make_notebook(session, make_course(session))
    asset = make_asset(session, book)
    material = make_material(session, book, asset)
    persist_ir(session, book, asset)
    previous_id = current_run(session, asset.id).id
    original_key = asset.storage_key
    material.status = 'failed'
    session.commit()
    response = switch_asset_processing_route(asset.id, ProcessingRouteSelection(processing_route='llm'), session)
    assert response['processing_route'] == 'llm'
    session.refresh(asset)
    session.refresh(material)
    assert asset.processing_route == material.processing_route == 'llm'
    assert material.status == 'pending'
    assert current_run(session, asset.id).id == previous_id
    assert asset.storage_key == original_key
