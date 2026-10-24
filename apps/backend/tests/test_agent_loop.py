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
            [_tool_call_event("propose_note_edits", '{"rationale": "补充例子", "edits": [{"op": "append", "content": "新段落"}]}')],
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


def test_run_agent_material_narrowing_wires_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """课件收窄链路：标题进提示词、id 进工具执行器；工具集裁掉覆盖率与跨课程工具。"""
    for db, ids in _world():
        captured: list[dict] = []

        class RecordingClient:
            last_usage = None

            def __init__(self, *args, **kwargs) -> None:
                self.configured = True

            def chat_stream(self, messages, *, tools=None, max_tokens=0, temperature=0.2):
                captured.append({"messages": [dict(message) for message in messages], "tools": tools})
                yield {"type": "delta", "text": "依据收窄后的课件作答。"}

        monkeypatch.setattr(agent_loop, "DeepSeekClient", RecordingClient)
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?",
            scope="course", material_id=ids["material_a"],
        ))
        final = events[-1]
        assert final["type"] == "final"
        tool_names = {spec["function"]["name"] for spec in captured[0]["tools"]}
        assert "get_note_coverage" not in tool_names
        assert "search_forest" not in tool_names
        user_message = next(message for message in captured[0]["messages"] if message["role"] == "user")
        assert "《第1讲 行列式》" in user_message["content"], "课件标题应写进教学上下文"


def test_run_agent_passes_material_id_to_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute_tool 必须收到收窄的 material_id：未带 material_id 的检索会被注入并只命中该课件。"""
    for db, ids in _world():
        captured_kwargs: list[dict] = []
        real_execute = agent_loop.execute_tool

        def spy(db_session, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return real_execute(db_session, **kwargs)

        monkeypatch.setattr(agent_loop, "execute_tool", spy)
        _install_fake_client(monkeypatch, [
            [_tool_call_event("search_course", '{"query": "行列式"}')],
            [{"type": "delta", "text": "完成。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?",
            scope="course", material_id=ids["material_a"],
        ))
        assert captured_kwargs and captured_kwargs[0]["material_id"] == ids["material_a"]
        final = events[-1]
        assert final["type"] == "final" and final["chunks"], "注入后应命中收窄课件的片段"


def test_run_agent_allow_note_discovery_wires_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """P4 发现开关透传：specs 注册发现版工具，执行器收到开关并按 note_id 提交建议。"""
    for db, ids in _world():
        captured: list[dict] = []
        real_execute = agent_loop.execute_tool

        def spy(db_session, **kwargs):
            captured.append(dict(kwargs))
            return real_execute(db_session, **kwargs)

        monkeypatch.setattr(agent_loop, "execute_tool", spy)
        _install_fake_client(monkeypatch, [
            [_tool_call_event("propose_note_edits",
                              f'{{"note_id": "{ids["note_a2"]}", "rationale": "补全矩阵笔记", "edits": [{{"op": "append", "content": "新段落"}}]}}')],
            [{"type": "delta", "text": "已为《矩阵》提交修改建议。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="把矩阵笔记补全一下",
            scope="global", allow_note_discovery=True,
        ))
        assert captured and captured[0]["allow_note_discovery"] is True
        final = events[-1]
        assert final["type"] == "final" and len(final["suggestions"]) == 1
        assert final["suggestions"][0]["note_title"] == "矩阵"
        db.flush()
        suggestion = db.get(NoteSuggestion, final["suggestions"][0]["id"])
        assert suggestion is not None and suggestion.status == "pending"
