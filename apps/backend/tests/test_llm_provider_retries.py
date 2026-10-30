"""Recover from blank JSON responses without hiding permanent provider errors."""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.core.config import settings
from app.document_processing.checkpoints import structured_call


def client():
    return DeepSeekClient(replace(settings, deepseek_api_key='test-key',
                                 deepseek_base_url='https://provider.test'))


def response(content, finish_reason='stop', status=200):
    return httpx.Response(status, request=httpx.Request('POST', 'https://provider.test/chat/completions'),
        json={'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}],
              'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}})


@pytest.mark.parametrize('blank', [None, '', '   \n '])
def test_blank_json_response_is_retried_then_returns_real_result(blank, monkeypatch):
    responses = iter([response(blank), response('{"units": []}')])
    requests, sleeps = [], []
    def post(*args, **kwargs):
        requests.append(kwargs['json'])
        return next(responses)
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', sleeps.append)
    provider = client()
    result = structured_call(provider, [{'role': 'user', 'content': 'Return JSON'}], max_tokens=6000)
    assert result == {'units': []}
    assert len(requests) == 2
    assert all(item['max_tokens'] == 6000 for item in requests)
    assert sleeps == [1]
    assert provider.last_usage == {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}


def test_persistent_blank_json_stops_after_three_attempts(monkeypatch):
    calls, sleeps = [], []
    def post(*args, **kwargs):
        calls.append(1)
        return response(' ')
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', sleeps.append)
    with pytest.raises(DeepSeekError) as captured:
        structured_call(client(), [{'role': 'user', 'content': 'Return JSON'}])
    assert captured.value.code == 'provider_empty'
    assert len(calls) == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize('status', [401, 402])
def test_authentication_and_credit_errors_are_not_retried(status, monkeypatch):
    calls, sleeps = [], []
    def post(*args, **kwargs):
        calls.append(1)
        return response(None, status=status)
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', sleeps.append)
    with pytest.raises(DeepSeekError) as captured:
        structured_call(client(), [{'role': 'user', 'content': 'Return JSON'}])
    assert captured.value.status_code == status
    assert len(calls) == 1
    assert sleeps == []


def test_blank_output_with_length_finish_stops_after_bounded_budget_growth(monkeypatch):
    calls, sleeps = [], []
    def post(*args, **kwargs):
        calls.append(kwargs['json']['max_tokens'])
        return response('', finish_reason='length')
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', sleeps.append)
    with pytest.raises(DeepSeekError) as captured:
        structured_call(client(), [{'role': 'user', 'content': 'Return JSON'}])
    assert captured.value.code == 'output_truncated'
    assert calls == [8000, 16000, 32000]
    assert sleeps == []


def test_truncated_reasoning_and_partial_json_get_more_budget_without_accepting_partial_result(monkeypatch):
    responses = iter([response('', finish_reason='length'),
                      response('{"units": [', finish_reason='length'),
                      response('{"units": []}')])
    budgets, sleeps = [], []
    def post(*args, **kwargs):
        budgets.append(kwargs['json']['max_tokens'])
        return next(responses)
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', sleeps.append)
    result = structured_call(client(), [{'role': 'user', 'content': 'Return JSON'}], max_tokens=6000)
    assert result == {'units': []}
    assert budgets == [6000, 12000, 24000]
    assert sleeps == []


def test_truncated_output_budget_never_exceeds_cap(monkeypatch):
    budgets = []
    def post(*args, **kwargs):
        budgets.append(kwargs['json']['max_tokens'])
        return response('', finish_reason='length')
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr('time.sleep', lambda _: pytest.fail('Truncation is not a transport retry'))
    with pytest.raises(DeepSeekError) as captured:
        structured_call(client(), [{'role': 'user', 'content': 'Return JSON'}], max_tokens=20000)
    assert captured.value.code == 'output_truncated'
    assert budgets == [20000, 32000]
