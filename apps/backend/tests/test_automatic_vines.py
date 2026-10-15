import json

import pytest
from sqlalchemy import select
from test_forest_jobs import _newer_unrelated_notes, _notes, _run
from test_forest_jobs import setup as forest_setup

from app.db.models import CrossCourseRelation, ForestJob
from app.forest import jobs

setup = forest_setup


def test_all_source_notes_are_persisted_and_processed_in_bounded_batches(setup, monkeypatch):
    _, db, factory = setup
    notes = _notes(db)
    _newer_unrelated_notes(db, notes[0], count=61)
    seen = []
    monkeypatch.setattr(jobs.DeepSeekClient, 'configured', property(lambda self: True))

    def response(self, messages, **kwargs):
        payload = json.loads(messages[1]['content'])
        assert 0 < len(payload['source']) <= 30
        assert len(payload['candidates']) <= 18
        seen.extend(row['note_id'] for row in payload['source'])
        return {'relations': []}

    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', response)
    job = jobs.enqueue_relations(db, notes[0].course_id, material_id=notes[0].material_id)
    db.commit()
    assert len(json.loads(job.source_snapshot_json)) == 62
    _run(factory, monkeypatch)
    assert len(seen) == len(set(seen)) == 62
    db.refresh(job)
    assert job.status == 'completed'


def test_valid_result_is_automatic_hidden_stays_hidden_and_explicit_restore_is_manual(setup, monkeypatch):
    from test_forest_jobs import _current_ai_relations
    client, db, factory = setup
    notes = _notes(db)
    _current_ai_relations(monkeypatch, notes)
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    relation = client.get('/api/v1/forest/relations').json()[0]
    assert relation['activation_mode'] == 'automatic'
    path = '/api/v1/forest/relations/' + relation['id']
    assert client.delete(path).status_code == 200
    assert client.get('/api/v1/forest/relations').json() == []
    notes[0].revision_number += 1
    db.commit()
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    assert client.get('/api/v1/forest/relations').json() == []
    assert db.scalar(select(CrossCourseRelation)).status == 'rejected'
    restored = client.post('/api/v1/forest/relations', json={
        'source_note_id': notes[0].id, 'target_note_id': notes[1].id,
        'relation_type': 'application', 'reason': '主动恢复并核对来源'})
    assert restored.status_code == 201
    assert restored.json()['id'] == relation['id']
    assert restored.json()['activation_mode'] == 'manual'


def test_source_change_without_body_revision_has_new_durable_identity(setup):
    _, db, _ = setup
    notes = _notes(db)
    first = jobs.enqueue_relations(db, notes[0].course_id)
    first.status = 'completed'
    db.commit()
    notes[0].source_refs[0].quote = '矩阵乘法'
    db.commit()
    second = jobs.enqueue_relations(db, notes[0].course_id)
    assert first.id != second.id
    assert notes[0].revision_number == 5 and notes[0].user_locked


def test_saved_user_edits_coalesce_latest_revision_without_overwriting_body(setup):
    from app.notes.service import update_note_as_user
    _, db, _ = setup
    notes = _notes(db)
    update_note_as_user(db, notes[0], '第一次用户保存', 5)
    update_note_as_user(db, notes[0], '第二次用户保存', 6)
    pending = list(db.scalars(select(ForestJob).where(ForestJob.status == 'pending')))
    assert len(pending) == 1
    assert json.loads(pending[0].source_snapshot_json)[0]['revision'] == 7
    assert notes[0].content_markdown == '第二次用户保存' and notes[0].user_locked


def test_legacy_pending_revalidated_in_background_without_model_and_rejection_preserved(setup, monkeypatch):
    client, db, factory = setup
    notes = _notes(db)
    relation = CrossCourseRelation(
        source_course_id=notes[0].course_id, target_course_id=notes[1].course_id,
        source_note_id=notes[0].id, target_note_id=notes[1].id,
        source_revision=5, target_revision=5, relation_type='application', reason='old inference',
        source_ref_ids_json=json.dumps([notes[0].source_refs[0].id]),
        target_ref_ids_json=json.dumps([notes[1].source_refs[0].id]))
    db.add(relation)
    db.commit()
    monkeypatch.setattr(jobs, 'SessionLocal', factory)
    claimed = jobs.claim_next_forest_job()
    assert claimed is not None
    jobs.process_forest_job(claimed)
    row = client.get('/api/v1/forest/relations').json()[0]
    assert row['activation_mode'] == 'automatic' and not row['stale']


def test_source_quote_change_during_model_call_rejects_commit(setup, monkeypatch):
    from test_forest_jobs import _current_ai_relations
    _, db, factory = setup
    notes = _notes(db)
    _current_ai_relations(monkeypatch, notes)
    response = jobs.DeepSeekClient.complete_json
    def changed(self, messages, **kwargs):
        result = response(self, messages, **kwargs)
        notes[0].source_refs[0].quote = '矩阵乘法'
        db.commit()
        return result
    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', changed)
    job = jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    db.refresh(job)
    assert job.status == 'failed'
    assert list(db.scalars(select(CrossCourseRelation))) == []


def test_retry_resumes_committed_batches_and_refreshes_changed_snapshot(setup, monkeypatch):
    _, db, factory = setup
    notes = _notes(db)
    _newer_unrelated_notes(db, notes[0], count=31)
    monkeypatch.setattr(jobs.DeepSeekClient, 'configured', property(lambda self: True))
    seen = []
    def response(self, messages, **kwargs):
        payload = json.loads(messages[1]['content'])
        if seen and len(seen) == 30:
            raise jobs.DeepSeekError('fake unavailable')
        seen.extend(row['note_id'] for row in payload['source'])
        return {'relations': []}
    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', response)
    job = jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    db.refresh(job)
    assert job.status == 'failed' and job.completed_source_count == 30
    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', lambda self, messages, **kwargs: {'relations': []})
    jobs.retry_job(db, job)
    _run(factory, monkeypatch)
    db.refresh(job)
    assert job.status == 'completed' and job.completed_source_count == 32


def test_hide_during_model_call_cannot_be_overwritten_by_automatic_refresh(setup, monkeypatch):
    from test_forest_jobs import _current_ai_relations
    client, db, factory = setup
    notes = _notes(db)
    _current_ai_relations(monkeypatch, notes)
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    relation = client.get('/api/v1/forest/relations').json()[0]
    notes[0].revision_number += 1
    db.commit()
    original = jobs.DeepSeekClient.complete_json
    def response(self, messages, **kwargs):
        assert client.delete('/api/v1/forest/relations/' + relation['id']).status_code == 200
        return original(self, messages, **kwargs)
    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', response)
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    assert client.get('/api/v1/forest/relations').json() == []
    hidden = client.get('/api/v1/forest/relations?status=rejected').json()[0]
    assert hidden['id'] == relation['id'] and hidden['source_revision'] == 5


def test_retry_replaces_obsolete_source_snapshot_after_user_save(setup, monkeypatch):
    from test_forest_jobs import _current_ai_relations
    _, db, factory = setup
    notes = _notes(db)
    job = jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)  # Unconfigured model, durable failure.
    notes[0].revision_number = 6
    db.commit()
    _current_ai_relations(monkeypatch, notes)
    db.refresh(job)
    jobs.retry_job(db, job)
    _run(factory, monkeypatch)
    db.refresh(job)
    assert job.status == 'completed'
    assert json.loads(job.source_snapshot_json)[0]['revision'] == 6


@pytest.mark.parametrize('change', ['saved_revision', 'new_first_id'])
def test_retry_then_pending_merge_reanalyses_changed_source_before_old_checkpoint(setup, monkeypatch, change):
    from app.db.models import Note
    from app.notes.service import update_note_as_user
    _, db, factory = setup
    notes = _notes(db)
    _newer_unrelated_notes(db, notes[0], count=31)
    monkeypatch.setattr(jobs.DeepSeekClient, 'configured', property(lambda self: True))
    calls = 0
    seen = []

    def response(self, messages, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise jobs.DeepSeekError('fake interrupted second batch')
        seen.extend((row['note_id'], row['revision']) for row in json.loads(messages[1]['content'])['source'])
        return {'relations': []}

    monkeypatch.setattr(jobs.DeepSeekClient, 'complete_json', response)
    job = jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    db.refresh(job)
    assert job.status == 'failed' and job.completed_source_count == 30
    jobs.retry_job(db, job)
    first_id = json.loads(job.source_snapshot_json)[0]['note_id']
    first = db.get(Note, first_id)
    if change == 'saved_revision':
        update_note_as_user(db, first, 'user saved after retry', first.revision_number)
        expected = (first.id, first.revision_number)
    else:
        added = Note(id='000-new-source', course_id=first.course_id,
                     material_id=first.material_id, knowledge_node_id=first.knowledge_node_id,
                     title='new source before checkpoint', content_markdown='new source',
                     source_refs=list(first.source_refs))
        db.add(added)
        db.flush()
        jobs.enqueue_relations(db, first.course_id, note_ids=[added.id])
        db.commit()
        expected = (added.id, added.revision_number)
    db.refresh(job)
    assert job.completed_source_count == 0 and job.progress == 0
    seen.clear()
    _run(factory, monkeypatch)
    db.refresh(job)
    assert expected in seen
    assert set(seen) == {(row['note_id'], row['revision']) for row in json.loads(job.source_snapshot_json)}
    assert job.status == 'completed'


def test_relation_response_versions_source_changes_without_note_or_ref_identity_changes(setup, monkeypatch):
    from test_forest_jobs import _current_ai_relations
    client, db, factory = setup
    notes = _notes(db)
    _current_ai_relations(monkeypatch, notes)
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    before = client.get('/api/v1/forest/relations').json()[0]
    assert before['evidence_fingerprint']
    notes[0].source_refs[0].quote = '矩阵乘法'
    db.commit()
    jobs.enqueue_relations(db, notes[0].course_id)
    db.commit()
    _run(factory, monkeypatch)
    after = client.get('/api/v1/forest/relations').json()[0]
    assert after['id'] == before['id'] and after['source_ref_ids'] == before['source_ref_ids']
    assert after['source_revision'] == before['source_revision'] and not after['stale']
    assert after['evidence_fingerprint'] != before['evidence_fingerprint']
