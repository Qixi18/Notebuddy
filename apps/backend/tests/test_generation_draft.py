"""Compact teaching drafts compile locally; models do not build editor trees."""
from __future__ import annotations

import copy
import json

import pytest

from app.generation.composer import CompositionError


def test_compile_teaching_blocks_and_exact_evidence():
    from app.generation.draft import compile_draft
    from app.notes.document import validate_document
    data = {'blocks': [
        {'kind': 'heading', 'text': '导数', 'level': 2, 'sources': ['s1']},
        {'kind': 'paragraph', 'parts': [{'text': '定义为 '}, {'latex': r'f\prime(x)'}], 'sources': ['s1']},
        {'kind': 'equation', 'latex': r'\frac{d}{dx}x^2=2x', 'sources': ['s1']},
        {'kind': 'list', 'items': [[{'text': '注意定义域'}], [{'latex': 'x>0'}]], 'sources': ['s1']},
        {'kind': 'table', 'rows': [['x', 'y'], [[{'latex': 'x^2'}], '4']], 'sources': ['s1']},
        {'kind': 'callout', 'title': '注意', 'parts': [{'text': '先核对条件'}], 'sources': ['s1']},
        {'kind': 'example', 'title': '例题', 'parts': [{'text': '求变化率'}], 'sources': ['s1']},
    ]}
    original = copy.deepcopy(data)
    result = compile_draft(data, {'s1': 'actual-long-source-id'})
    assert data == original
    validate_document({'type': 'doc', 'content': result.nodes})
    assert [node['type'] for node in result.nodes] == [
        'heading', 'paragraph', 'blockMath', 'bulletList', 'table', 'callout', 'example']
    assert result.nodes[1]['content'][1] == {'type': 'inlineMath', 'attrs': {'latex': r'f\prime(x)'}}
    assert result.nodes[2]['attrs']['latex'] == r'\frac{d}{dx}x^2=2x'
    assert list(result.source_map.values()) == [['actual-long-source-id']] * 7


@pytest.mark.parametrize('block', [
    {'kind': 'paragraph', 'text': 'No source'},
    {'kind': 'paragraph', 'parts': [{'text': 'Invented'}], 'sources': ['fake']},
    {'kind': 'paragraph', 'parts': [{'text': 'x', 'latex': 'y'}], 'sources': ['s1']},
    {'kind': 'equation', 'latex': r'\href{https://example.test}{x}', 'sources': ['s1']},
    {'kind': 'equation', 'latex': r'\frac{x}{', 'sources': ['s1']},
    {'kind': 'equation', 'latex': 'x' * 2001, 'sources': ['s1']},
    {'kind': 'table', 'rows': [], 'sources': ['s1']},
    {'kind': 'image', 'text': 'untrusted', 'sources': ['s1']},
    {'kind': 'heading', 'text': '', 'sources': ['s1']},
])
def test_invalid_draft_is_rejected_without_partial_output(block):
    from app.generation.draft import compile_draft
    with pytest.raises(CompositionError):
        compile_draft({'blocks': [block]}, {'s1': 'real'})


@pytest.mark.parametrize('latex', ['$x+y$', '$$x+y$$', r'\(x+y\)', r'\[x+y\]'])
def test_draft_strips_only_one_complete_formula_wrapper(latex):
    from app.generation.draft import compile_draft
    result = compile_draft({'blocks': [{'kind': 'equation', 'latex': latex, 'sources': ['s1']}]}, {'s1': 'real'})
    assert result.nodes[0]['attrs']['latex'] == 'x+y'


def test_hybrid_composer_uses_short_sources_and_compiles_without_model_tree(monkeypatch):
    from app.document_processing import config
    from app.generation.composer import compose_deepseek
    from app.generation.planner import build_plan
    from tests.test_generation_limits import _client, _response, _snapshot
    calls = []
    def answer(payload):
        content = json.loads(payload['messages'][1]['content'])
        blocks = [b for unit in content['units'] for b in unit['blocks']]
        calls.append(content)
        assert blocks[0]['block_id'] == 's1'
        assert 'attrs.blockId' not in payload['messages'][0]['content']
        return _response(json.dumps({'blocks': [{'kind': 'paragraph',
            'parts': [{'text': blocks[0]['text']}], 'sources': ['s1']}]}))
    client = _client(monkeypatch, answer)
    monkeypatch.setattr(config, 'provider_client', lambda _: client)
    source = _snapshot(blocks=1)
    source['processing_route'] = 'llm'
    source['provider'] = {'reading_mode': 'hybrid'}
    plan = build_plan(source)
    result = compose_deepseek(source, plan, plan['batches'][0])
    assert len(calls) == 1
    assert list(result.source_map.values()) == [['b0']]
    assert result.generator_version == 'draft-v1'
