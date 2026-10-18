"""agent 循环测试：事件序列、建议产出、轮次上限与失败降级。

用伪造的 DeepSeekClient 脚本化每轮事件，不访问真实服务；
课程数据复用 ``test_agent_tools._build_world`` 的双课程夹具。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_agent_tools import _build_world

from app.ai import agent_loop
from app.db.database import Base
from app.db.models import NoteSuggestion


def _world():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _build_world(db)
        yield db, ids


def _tool_call_event(name: str, arguments: str, *, reasoning: str | None = None) -> dict:
    return {
        "type": "tool_calls",
        "reasoning_content": reasoning,
        "tool_calls": [{"id": "call_1", "name": name, "arguments": arguments}],
    }


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, rounds: list[list[dict]], *, configured: bool = True) -> list[list[dict]]:
    class FakeClient:
        last_usage = None

        def __init__(self, *args, **kwargs) -> None:
            self.configured = configured

        def chat_stream(self, messages, *, tools=None, max_tokens=0, temperature=0.2):
            yield from rounds.pop(0)

    monkeypatch.setattr(agent_loop, "DeepSeekClient", FakeClient)
    return rounds


def test_run_agent_streams_steps_deltas_and_final(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids in _world():
        rounds = _install_fake_client(monkeypatch, [
            [{"type": "delta", "text": "先查一下课件。"},
             _tool_call_event("search_course", '{"query": "行列式"}', reasoning="需要课件依据")],
            [{"type": "delta", "text": "行列式是线性代数的基本工具。"}],
        ])
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?"))
        assert rounds == [], "脚本轮次应被耗尽"

        types = [event["type"] for event in events]
        assert types.count("step") == 2, "一个工具调用应有 running + done 两条时间线"
        assert types[0] == "delta" and types[-1] == "final"
        final = events[-1]
        assert final["answer"] == "先查一下课件。行列式是线性代数的基本工具。", "最终回答应包含全部轮次文本"
        assert final["mode"] == "agent" and final["model_version"]
        assert final["chunks"], "工具真实执行后应收集到课件片段作为证据"


def test_run_agent_collects_note_edit_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids in _world():
        _install_fake_client(monkeypatch, [
            [_tool_call_event("propose_note_edit", '{"proposed_markdown": "# 行列式\\n新全文", "rationale": "补充例子"}')],
            [{"type": "delta", "text": "已提交修改建议，请点采纳。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="帮我把这篇笔记整理一下",
            scope="note", locked_note_id=ids["note_a1"], editable_note_id=ids["note_a1"],
        ))
        final = events[-1]
        assert final["type"] == "final"
        assert len(final["suggestions"]) == 1
        assert final["suggestions"][0]["type"] == "note_suggestion"
        db.flush()
        suggestion = db.get(NoteSuggestion, final["suggestions"][0]["id"])
        assert suggestion is not None and suggestion.status == "pending"


def test_run_agent_without_key_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids in _world():
        _install_fake_client(monkeypatch, [], configured=False)
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="问题"))
        assert events == [{"type": "error", "message": "AI 模型未配置，无法启动智能模式"}]


def test_run_agent_stops_at_round_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids in _world():
        endless = [[_tool_call_event("search_course", '{"query": "循环"}')] for _ in range(agent_loop.MAX_TOOL_ROUNDS)]
        _install_fake_client(monkeypatch, endless)
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="反复检索"))
        assert events[-1] == {"type": "error", "message": f"工具调用轮次达到上限（{agent_loop.MAX_TOOL_ROUNDS} 轮），已停止执行"}


def test_run_agent_tool_failure_degrades_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids in _world():
        _install_fake_client(monkeypatch, [
            [_tool_call_event("search_course", '{"query": "行列式", "material_id": "not-exist"}')],
            [{"type": "delta", "text": "检索失败，我直接说明已知内容。"}],
        ])
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?"))
        steps = [event for event in events if event["type"] == "step" and event["status"] == "done"]
        assert steps and "不属于当前课程" in steps[0]["detail"], "工具失败应折算为时间线文本而不是断流"
        assert events[-1]["type"] == "final"
