import json

import pytest

from app.forest.notebook_relations import enqueue_notebook_relations
from app.notes.store import write_document
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ['tests.notebook_fixtures']


def test_ai_relation_snapshot_includes_sections_beyond_standard_candidate_cap(session):
    books = []
    for name, count in [('source', 1), ('target', 31)]:
        book = make_notebook(session, make_course(session, name))
        nodes = []
        for n in range(count):
            nodes.extend([
                {'type': 'heading', 'attrs': {'blockId': f'h{n}', 'level': 1},
                 'content': [{'type': 'text', 'text': f'Independent concept {n}'}]},
                {'type': 'paragraph', 'attrs': {'blockId': f'p{n}'},
                 'content': [{'type': 'text', 'text': f'This course explains concept number {n}.'}]},
            ])
        write_document(session, book, {'type': 'doc', 'content': nodes}, expected_revision=0)
        books.append(book)
    session.commit()
    job = enqueue_notebook_relations(session, books[0].course_id, processing_route='llm')
    snapshot = json.loads(job.source_snapshot_json)
    assert len(snapshot['targets']) == 31
    assert snapshot['processing_route'] == 'llm'


def test_model_relations_visit_all_targets_and_reject_invented_endpoint():
    from app.forest.llm_relations import propose_relations
    snapshot = {'sources': [{'key': 's0', 'excerpt': 'Derivatives express local change.'}],
                'targets': [{'key': f't{n}', 'excerpt': f'Explanation of target {n}.'} for n in range(31)]}
    visited = set()
    def provider(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        if isinstance(payload, list):
            return {'summary': 'A grounded summary.'}
        visited.update(row['key'] for row in payload['targets'])
        return {'relations': []}
    assert propose_relations(snapshot, provider) == []
    assert visited == {f't{n}' for n in range(31)}
    with pytest.raises(ValueError, match='输入之外'):
        propose_relations(snapshot, lambda *a, **k: {'relations': [
            {'source_key': 's0', 'target_key': 'foreign', 'relation_type': 'related', 'reason': 'invented'}]})
