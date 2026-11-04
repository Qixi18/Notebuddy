from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import FileProcessingBudget, ProviderUsageReservation
from app.services import processing_budget as budget


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'budget.sqlite3'}", connect_args={'timeout': 15})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(budget, 'SessionLocal', factory)
    today = datetime.now(UTC).date().isoformat()
    for key, value in {
        'DEEPSEEK_MODEL': 'text-test', 'DEEPSEEK_INPUT_COST_PER_MILLION': '1000',
        'DEEPSEEK_OUTPUT_COST_PER_MILLION': '1000', 'DEEPSEEK_PRICE_VERSION': 'test-1',
        'DEEPSEEK_PRICE_SOURCE': 'https://prices.example/text',
        'NOTEBOOK_VISION_MODEL': 'vision-test', 'NOTEBOOK_VISION_INPUT_COST_PER_MILLION': '1000',
        'NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION': '1000', 'NOTEBOOK_VISION_MAX_IMAGE_TOKENS': '1000',
        'NOTEBOOK_VISION_PRICE_VERSION': 'vision-1', 'NOTEBOOK_VISION_PRICE_SOURCE': 'https://prices.example/vision',
        'NOTEBOOK_BUDGET_USD_CNY_RATE': '1', 'NOTEBOOK_BUDGET_FX_RATE_SOURCE': 'https://fx.example/rates',
        'NOTEBOOK_BUDGET_FX_RATE_AS_OF': today, 'NOTEBOOK_BUDGET_FX_BUFFER_PERCENT': '0',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(budget, 'BUDGET_LIMIT_FEN', 5000)
    yield factory
    engine.dispose()


def reserve(asset_ids, *, max_tokens=40_000, kind='text', messages=None):
    with budget.processing_budget_scope(asset_ids=asset_ids, notebook_id='book-1',
            stage='test', job_id='job-1', kind=kind):
        guard = budget.active_budget_guard()
        return guard.before_request(provider='fake', model='vision-test' if kind == 'vision' else 'text-test',
            messages=messages or [{'role': 'user', 'content': 'hello'}], max_tokens=max_tokens)


def test_price_snapshot_is_required_and_expiry_fails_closed(ledger, monkeypatch):
    budget.ensure_budget_ready('text')
    monkeypatch.setenv('DEEPSEEK_PRICE_VERSION', '')
    with pytest.raises(budget.ProcessingBudgetError, match='版本号'):
        budget.ensure_budget_ready('text')
    monkeypatch.setenv('DEEPSEEK_PRICE_VERSION', 'test-1')
    monkeypatch.setenv('NOTEBOOK_BUDGET_FX_RATE_AS_OF', '2000-01-01')
    with pytest.raises(budget.ProcessingBudgetError, match='有效期'):
        budget.ensure_budget_ready('text')


def test_reservation_settlement_and_one_time_accounting(ledger):
    reservation = reserve(['asset-a'], max_tokens=40_000)
    assert reservation['reserved_fen'] == 4055
    with budget.processing_budget_scope(asset_ids=['asset-a'], notebook_id='book-1',
            stage='test', job_id='job-1'):
        budget.active_budget_guard().after_response(reservation, {'prompt_tokens': 10, 'completion_tokens': 10})
    with budget.SessionLocal() as db:
        row = db.get(FileProcessingBudget, 'asset-a')
        entry = db.scalar(select(ProviderUsageReservation).where(ProviderUsageReservation.call_id == reservation['call_id']))
        assert row.settled_fen == 2 and row.reserved_fen == 0
        assert entry.state == 'settled' and entry.charged_fen == 2
        with pytest.raises(budget.ProcessingBudgetError, match='状态不一致'):
            budget._settle(reservation, {'prompt_tokens': 10, 'completion_tokens': 10})


def test_missing_usage_marks_asset_uncertain_and_retains_reservation(ledger):
    reservation = reserve(['asset-a'], max_tokens=40_000)
    with pytest.raises(budget.ProcessingBudgetError, match='未返回完整'):
        budget._settle(reservation, None)
    state = budget.budget_read('asset-a')
    assert state['status'] == 'uncertain'
    assert state['reserved_fen'] == reservation['reserved_fen']
    with pytest.raises(budget.ProcessingBudgetError, match='已阻止'):
        reserve(['asset-a'], max_tokens=1)


def test_provider_overrun_is_charged_and_permanently_gated(ledger):
    reservation = reserve(['asset-a'], max_tokens=1)
    with pytest.raises(budget.ProcessingBudgetError) as exc:
        budget._settle(reservation, {'prompt_tokens': 10, 'completion_tokens': 100_000})
    assert exc.value.code == 'budget_overrun'
    state = budget.budget_read('asset-a')
    assert state['status'] == 'overrun'
    assert state['settled_fen'] > reservation['reserved_fen']


def test_shared_call_reserves_full_amount_against_each_asset(ledger):
    reservation = reserve(['asset-a', 'asset-b'], max_tokens=40_000)
    assert reservation['reserved_fen'] == 4055
    assert budget.budget_read('asset-a')['reserved_fen'] == 4055
    assert budget.budget_read('asset-b')['reserved_fen'] == 4055


def test_concurrent_reservations_cannot_overspend_one_asset(ledger):
    def compete(_):
        try:
            return reserve(['asset-a'], max_tokens=40_000)['call_id']
        except budget.ProcessingBudgetError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, range(2)))
    assert sum(isinstance(value, str) and value not in {'budget_exhausted', 'budget_uncertain'} for value in outcomes) == 1
    state = budget.budget_read('asset-a')
    assert state['reserved_fen'] == 4055
    assert state['status'] == 'exhausted'


def test_deepseek_fake_provider_is_metered_before_return(ledger, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.core.config import settings

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                    'usage': {'prompt_tokens': 12, 'completion_tokens': 4, 'total_tokens': 16}}

    calls = []
    monkeypatch.setattr('app.ai.deepseek.httpx.post', lambda *args, **kwargs: calls.append(kwargs) or Response())
    from copy import copy
    client_settings = copy(settings)
    client_settings.deepseek_api_key = 'fake-provider-key'
    client_settings.deepseek_model = 'text-test'
    client_settings.deepseek_base_url = 'https://fake-provider.invalid/v1'
    client = DeepSeekClient(client_settings)
    with budget.processing_budget_scope(asset_ids=['asset-a'], notebook_id='book-1', stage='compose'):
        assert client.complete([{'role': 'user', 'content': 'local fake test'}], max_tokens=100) == 'ok'
    state = budget.budget_read('asset-a')
    assert len(calls) == 1
    assert state['status'] == 'active'
    assert state['reserved_fen'] == 0
    assert state['settled_fen'] > 0


def test_provider_timeout_marks_uncertain_and_prevents_retry_dispatch(ledger, monkeypatch):
    import httpx

    from app.ai.deepseek import DeepSeekClient, DeepSeekError
    from app.core.config import settings
    from app.document_processing.checkpoints import structured_call

    calls = []
    def timeout(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ReadTimeout('fake timeout')
    monkeypatch.setattr('app.ai.deepseek.httpx.post', timeout)
    from copy import copy
    client_settings = copy(settings)
    client_settings.deepseek_api_key = 'fake-provider-key'
    client_settings.deepseek_model = 'text-test'
    client_settings.deepseek_base_url = 'https://fake-provider.invalid/v1'
    client = DeepSeekClient(client_settings)
    with (budget.processing_budget_scope(asset_ids=['asset-a'], notebook_id='book-1', stage='plan'),
          pytest.raises(DeepSeekError)):
        structured_call(client, [{'role': 'user', 'content': 'fake'}], max_tokens=100)
    state = budget.budget_read('asset-a')
    assert len(calls) == 1
    assert state['status'] == 'uncertain'
    assert state['reserved_fen'] > 0
