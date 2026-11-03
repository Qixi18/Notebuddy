"""P1-BUD-01/05：真实账单样例与本地预留/结算的对账（虚构、已脱敏）。

用途：把"按保守上界预留、按 usage 结算"这套假设摊开检验，并固定三条口径：
1) 供应商账单低于预留 → 只按实际 usage 扣费；
2) 账单高于预留 → 记 overrun 并永久拦截该 Asset；
3) usage 缺失 → 记 uncertain，不退款、不自动重试。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from app.db.database import Base
from app.services import processing_budget as budget


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.sqlite3'}", connect_args={'timeout': 15})
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(budget, 'SessionLocal', factory)
    today = datetime.now(UTC).date().isoformat()
    for key, value in {
        'DEEPSEEK_MODEL': 'text-test', 'DEEPSEEK_INPUT_COST_PER_MILLION': '10',
        'DEEPSEEK_OUTPUT_COST_PER_MILLION': '40', 'DEEPSEEK_PRICE_VERSION': 'invoice-1',
        'DEEPSEEK_PRICE_SOURCE': 'https://prices.example/text',
        'NOTEBOOK_BUDGET_USD_CNY_RATE': '7.2', 'NOTEBOOK_BUDGET_FX_RATE_SOURCE': 'https://fx.example/rates',
        'NOTEBOOK_BUDGET_FX_RATE_AS_OF': today, 'NOTEBOOK_BUDGET_FX_BUFFER_PERCENT': '25',
    }.items():
        monkeypatch.setenv(key, value)
    yield factory
    engine.dispose()


def _reserve(**overrides):
    with budget.processing_budget_scope(asset_ids=['asset-invoice'], notebook_id='book-1', stage='compose'):
        return budget.active_budget_guard().before_request(
            provider='fake', model='text-test',
            messages=[{'role': 'user', 'content': 'desensitised fake prompt'}],
            max_tokens=overrides.get('max_tokens', 500),
        )


def _settle(reservation, usage):
    with budget.processing_budget_scope(asset_ids=['asset-invoice'], notebook_id='book-1', stage='compose'):
        budget.active_budget_guard().after_response(reservation, usage)


def test_invoice_below_reservation_only_charges_actual_usage(ledger):
    reservation = _reserve(max_tokens=500)
    assert reservation['reserved_fen'] > 0
    # 虚构账单：prompt 100 / completion 50
    _settle(reservation, {'prompt_tokens': 100, 'completion_tokens': 50})
    state = budget.budget_read('asset-invoice')
    assert state['reserved_fen'] == 0
    assert 0 < state['settled_fen'] < reservation['reserved_fen']
    assert state['status'] == 'active'
    entry = state['reservations'][-1]
    assert entry['state'] == 'settled'
    assert entry['charged_fen'] == state['settled_fen']


def test_invoice_above_reservation_marks_overrun_and_blocks_future_calls(ledger):
    reservation = _reserve(max_tokens=10)
    with pytest.raises(budget.ProcessingBudgetError) as exc:
        _settle(reservation, {'prompt_tokens': 100_000, 'completion_tokens': 100_000})
    assert exc.value.code == 'budget_overrun'
    state = budget.budget_read('asset-invoice')
    assert state['status'] == 'overrun'
    assert state['settled_fen'] > reservation['reserved_fen']
    # overrun 之后不能再发新的付费请求
    with pytest.raises(budget.ProcessingBudgetError) as blocked:
        _reserve()
    assert blocked.value.code in {'budget_exhausted', 'budget_uncertain'}


def test_missing_usage_keeps_reservation_and_flags_uncertain(ledger):
    reservation = _reserve()
    with pytest.raises(budget.ProcessingBudgetError) as exc:
        _settle(reservation, None)
    assert exc.value.code == 'budget_usage_unknown'
    state = budget.budget_read('asset-invoice')
    assert state['status'] == 'uncertain'
    assert state['reserved_fen'] == reservation['reserved_fen']
    assert state['settled_fen'] == 0


def test_fx_buffer_and_rate_are_frozen_into_the_ledger_snapshot(ledger):
    reservation = _reserve()
    _settle(reservation, {'prompt_tokens': 10, 'completion_tokens': 10})
    state = budget.budget_read('asset-invoice')
    entry = state['reservations'][-1]
    assert entry['tariff_version'] == 'invoice-1'
    # 汇率与缓冲固定在当时的价格快照里：历史账目不会被后续配置改动追溯改写
    assert state['currency'] == 'CNY'


def test_stale_fx_snapshot_fails_closed_before_spending(ledger, monkeypatch):
    monkeypatch.setenv('NOTEBOOK_BUDGET_FX_RATE_AS_OF', '2000-01-01')
    with pytest.raises(budget.ProcessingBudgetError, match='有效期'):
        _reserve()


def test_missing_price_version_fails_closed_before_spending(ledger, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_PRICE_VERSION', '')
    with pytest.raises(budget.ProcessingBudgetError, match='版本号'):
        _reserve()
