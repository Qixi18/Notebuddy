"""P1-BUD-01/02/03：单文件 10 元预算的端到端行为（Fake Provider，零真实付费）。

模拟真实处理链的收费阶段顺序：视觉读页 → 规划 → 正文生成 → 格式修复。
每个阶段都经过 `processing_budget_scope` + `DeepSeekClient`，与本机 Worker 的调用路径一致，
但不触网、不读用户数据。
"""

from __future__ import annotations

from copy import copy
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
        'NOTEBOOK_VISION_PRICE_VERSION': 'vision-1',
        'NOTEBOOK_VISION_PRICE_SOURCE': 'https://prices.example/vision',
        'NOTEBOOK_BUDGET_USD_CNY_RATE': '1', 'NOTEBOOK_BUDGET_FX_RATE_SOURCE': 'https://fx.example/rates',
        'NOTEBOOK_BUDGET_FX_RATE_AS_OF': today, 'NOTEBOOK_BUDGET_FX_BUFFER_PERCENT': '0',
    }.items():
        monkeypatch.setenv(key, value)
    # 测试把单文件上限压到 100 分，方便几轮就撞到上限
    monkeypatch.setattr(budget, 'BUDGET_LIMIT_FEN', 100)
    yield factory
    engine.dispose()


def _client(monkeypatch, *, prompt_tokens=10, completion_tokens=10):
    from app.ai.deepseek import DeepSeekClient
    from app.core.config import settings

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                    'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                              'total_tokens': prompt_tokens + completion_tokens}}

    calls: list[dict] = []
    monkeypatch.setattr('app.ai.deepseek.httpx.post',
                        lambda *args, **kwargs: calls.append(kwargs) or Response())
    client_settings = copy(settings)
    client_settings.deepseek_api_key = 'fake-provider-key'
    client_settings.deepseek_model = 'text-test'
    client_settings.deepseek_base_url = 'https://fake-provider.invalid/v1'
    return DeepSeekClient(client_settings), calls


def _run_stage(stage: str, client, *, asset_ids=('asset-a',), max_tokens=20) -> str:
    with budget.processing_budget_scope(
        asset_ids=list(asset_ids), notebook_id='book-1', stage=stage, job_id='job-1',
    ):
        return client.complete([{'role': 'user', 'content': stage}], max_tokens=max_tokens)


def test_all_stages_share_one_ledger_and_never_exceed_limit(ledger, monkeypatch):
    client, calls = _client(monkeypatch)
    for stage in ('vision_read', 'plan', 'compose', 'format_repair'):
        _run_stage(stage, client)

    with budget.SessionLocal() as db:
        rows = list(db.scalars(select(FileProcessingBudget)).all())
        entries = list(db.scalars(select(ProviderUsageReservation)).all())
    # 一个 Asset 只有一本账，四个阶段都记在同一本上
    assert len(rows) == 1
    assert rows[0].asset_id == 'asset-a'
    assert len(entries) == 4
    assert {entry.stage for entry in entries} == {'vision_read', 'plan', 'compose', 'format_repair'}
    state = budget.budget_read('asset-a')
    assert state['settled_fen'] > 0
    assert state['settled_fen'] + state['reserved_fen'] <= state['limit_fen']
    assert len(calls) == 4


def test_stage_is_blocked_before_dispatch_when_remaining_budget_too_small(ledger, monkeypatch):
    from app.ai.deepseek import DeepSeekError

    client, calls = _client(monkeypatch)
    _run_stage('compose', client, max_tokens=400)  # 一次几乎用尽 100 分
    before = len(calls)
    with pytest.raises(DeepSeekError) as exc:
        _run_stage('format_repair', client, max_tokens=20000)
    assert exc.value.code == 'budget_exhausted'
    # 关键：预算不足时根本没有发出网络请求
    assert len(calls) == before
    assert budget.budget_read('asset-a')['status'] == 'exhausted'


def test_retry_of_same_stage_does_not_reset_the_ledger(ledger, monkeypatch):
    client, _calls = _client(monkeypatch)
    _run_stage('compose', client, max_tokens=200)
    first = budget.budget_read('asset-a')
    _run_stage('compose', client, max_tokens=1)
    second = budget.budget_read('asset-a')
    assert second['settled_fen'] >= first['settled_fen']
    assert second['limit_fen'] == first['limit_fen']
    assert len(second['reservations']) == len(first['reservations']) + 1


def test_budget_survives_process_restart_like_session_recreation(ledger, monkeypatch):
    client, _calls = _client(monkeypatch)
    _run_stage('plan', client)
    settled = budget.budget_read('asset-a')['settled_fen']
    # 新连接、新会话（等价于 Worker 重启），账本仍是同一本
    with budget.SessionLocal() as db:
        row = db.get(FileProcessingBudget, 'asset-a')
        assert row is not None and row.settled_fen == settled
    _run_stage('compose', client)
    assert budget.budget_read('asset-a')['settled_fen'] > settled


def test_usage_missing_blocks_every_later_stage(ledger, monkeypatch):
    """usage 缺失 → uncertain；后续阶段必须先被拦住，不允许自动重试。"""

    reservation = _run_stage  # 占位，保持可读
    del reservation
    with budget.processing_budget_scope(asset_ids=['asset-a'], notebook_id='book-1', stage='compose'):
        guard = budget.active_budget_guard()
        held = guard.before_request(provider='fake', model='text-test',
                                    messages=[{'role': 'user', 'content': 'x'}], max_tokens=20)
        with pytest.raises(budget.ProcessingBudgetError, match='未返回完整'):
            guard.after_response(held, None)

    from app.ai.deepseek import DeepSeekError

    client, calls = _client(monkeypatch)
    before = len(calls)
    with pytest.raises(DeepSeekError) as exc:
        _run_stage('format_repair', client)
    assert exc.value.code in {'budget_uncertain', 'budget_exhausted'}
    assert len(calls) == before


def test_shared_assets_are_charged_individually_not_split(ledger, monkeypatch):
    client, _calls = _client(monkeypatch)
    _run_stage('compose', client, asset_ids=('asset-a', 'asset-b'))

    a = budget.budget_read('asset-a')
    b = budget.budget_read('asset-b')
    assert a['reservations'][-1]['reserved_fen'] == b['reservations'][-1]['reserved_fen']
    assert a['settled_fen'] == b['settled_fen']
    # 保守策略：一笔共享调用对每个 Asset 都记整笔，不做分摊
    assert a['settled_fen'] > 0
