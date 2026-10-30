"""AI planning must cover real evidence and cannot invent source identities."""
from __future__ import annotations

import json

import pytest


def snapshot():
    return {'processing_route': 'llm', 'notebook_title': 'Calculus', 'current_outline': [],
        'batch_chars': 18000, 'sources': [{'asset_id': 'a', 'name': 'book.pdf',
            'parse_run_id': 'r', 'sections': [{'section_id': 'p1', 'blocks': [
                {'block_id': 'b1', 'page_number': 1, 'text': 'A derivative is a rate of change.'},
                {'block_id': 'b2', 'page_number': 2, 'text': 'It is defined using a limit.'},
            ]}]}]}


def test_ai_selects_hierarchy_across_page_boundaries():
    from app.generation.llm_planner import build_llm_plan
    def model(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        assert {b['block_id'] for b in payload['blocks']} == {'b1', 'b2'}
        return {'units': [{'title': '变化率与极限', 'level': 2, 'intent': 'new',
                           'block_ids': ['b1', 'b2'], 'reason': '共同构成导数定义'}],
                'ignored': [], 'continuity': '下一节讨论导数的运算'}
    plan = build_llm_plan(snapshot(), model)
    assert plan['units'][0]['title'] == '变化率与极限'
    assert plan['units'][0]['level'] == 2
    assert plan['units'][0]['page_end'] == 2
    assert plan['batches'] == [['u1']]


@pytest.mark.parametrize('level', [4, 6, 9])
def test_deep_model_hierarchy_maps_to_editor_levels_without_losing_sources(level):
    from app.generation.llm_planner import build_llm_plan
    def model(*args, **kwargs):
        return {'units': [{'title': 'A nested concept', 'level': level, 'intent': 'new',
                           'block_ids': ['b1', 'b2'], 'reason': 'A detail of the parent topic',
                           'confidence': 0.9}]}
    plan = build_llm_plan(snapshot(), model)
    assert plan['units'][0]['level'] == 3
    assert plan['units'][0]['title'] == 'A nested concept'
    assert plan['units'][0]['block_ids'] == ['b1', 'b2']
    assert plan['batches'] == [['u1']]


@pytest.mark.parametrize('level', [0, -1])
def test_nonpositive_model_hierarchy_is_still_rejected(level):
    from pydantic import ValidationError

    from app.generation.llm_planner import build_llm_plan
    with pytest.raises(ValidationError):
        build_llm_plan(snapshot(), lambda *a, **k: {'units': [
            {'title': 'topic', 'level': level, 'intent': 'new',
             'block_ids': ['b1', 'b2'], 'reason': 'topic'}]})


@pytest.mark.parametrize('duplicate_ids', [False, True])
def test_formula_heavy_composition_batches_use_serialized_evidence_size(duplicate_ids):
    from app.generation.llm_planner import build_llm_plan
    source = snapshot()
    blocks = [{'block_id': f'b{number}', 'page_number': number, 'text': 'A formula',
               'latex': 'x' * 8000} for number in range(1, 4)]
    source['sources'][0]['sections'][0]['blocks'] = blocks
    def model(messages, **kwargs):
        group = json.loads(messages[-1]['content'])['blocks']
        identities = [block['block_id'] for block in group]
        if duplicate_ids:
            identities.insert(0, identities[0])
        return {'units': [{'title': 'Matrix formulas', 'level': 1, 'intent': 'new',
                           'block_ids': identities, 'reason': 'One topic'}]}
    plan = build_llm_plan(source, model)
    assert len(plan['batches']) == 2
    units = {unit['unit_id']: unit for unit in plan['units']}
    by_id = {block['block_id']: block for block in blocks}
    used = []
    for batch in plan['batches']:
        identities = [identity for unit_id in batch for identity in units[unit_id]['block_ids']]
        assert sum(len(json.dumps(by_id[identity], ensure_ascii=False)) for identity in identities) <= 18000
        used.extend(identities)
    assert used == ['b1', 'b2', 'b3']


@pytest.mark.parametrize('ids,ignored', [(['foreign'], []), (['b1'], [])])
def test_planner_rejects_invented_or_silently_dropped_sources(ids, ignored):
    from app.generation.llm_planner import build_llm_plan
    with pytest.raises(Exception, match='来源|覆盖'):
        build_llm_plan(snapshot(), lambda *a, **k: {'units': [
            {'title': 'topic', 'level': 1, 'intent': 'new', 'block_ids': ids, 'reason': 'topic'}],
            'ignored': ignored, 'continuity': ''})


def test_composition_retry_reuses_only_identical_successful_batch(session):
    from app.generation.composer import Composition, CompositionError
    from app.generation.resume import compose_batch
    calls = []
    def provider(snapshot, plan, batch, **kwargs):
        calls.append(batch)
        if batch == ['u2']:
            raise CompositionError('provider unavailable')
        return Composition(nodes=[{'type': 'paragraph', 'attrs': {'blockId': 'n1'},
                                   'content': [{'type': 'text', 'text': 'Note'}]}],
                           source_map={'n1': ['b1']}, generator='deepseek')
    source = snapshot()
    plan = {'units': [{'unit_id': 'u1', 'block_ids': ['b1']}]}
    result = compose_batch(session, 'job', source, plan, ['u1'], 'deepseek', compose_impl=provider)
    assert result.nodes[0]['content'][0]['text'] == 'Note'
    with pytest.raises(CompositionError):
        compose_batch(session, 'job', source, plan, ['u2'], 'deepseek', compose_impl=provider)
    session.rollback()
    restored = compose_batch(session, 'job', source, plan, ['u1'], 'deepseek', compose_impl=provider)
    assert list(restored.source_map.values()) == [['b1']]
    assert set(restored.source_map) == {restored.nodes[0]['attrs']['blockId']}
    assert calls == [['u1'], ['u2']]
    source['base_document_revision'] = 2
    compose_batch(session, 'job', source, plan, ['u1'], 'deepseek', compose_impl=provider)
    assert calls == [['u1'], ['u2'], ['u1']]


pytest_plugins = ['tests.notebook_fixtures']
