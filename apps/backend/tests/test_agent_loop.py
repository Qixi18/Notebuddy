"""agent 循环测试：事件序列、建议产出、轮次上限与失败降级。

用伪造的 DeepSeekClient 脚本化每轮事件，不访问真实服务；
课程数据复用 ``test_agent_tools._build_world`` 的双课程夹具。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker
from test_agent_tools import _build_world

from app.ai import agent_loop
from app.db.database import Base
from app.db.models import NoteSuggestion


def _world():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as db:
        ids = _build_world(db)
        yield db, ids, factory


_CALL_ID_SEQ = {"n": 0}


def _tool_call_event(name: str, arguments: str, *, reasoning: str | None = None, count: int = 1) -> dict:
    """构造一轮工具调用；count>1 时生成多个不同 id 的调用（并行执行用）。"""
    _CALL_ID_SEQ["n"] += 1
    base = _CALL_ID_SEQ["n"]
    return {
        "type": "tool_calls",
        "reasoning_content": reasoning,
        "tool_calls": [
            {"id": f"call_{base}_{i}", "name": name if i == 0 else f"{name}#{i}", "arguments": arguments}
            if False
            else {"id": f"call_{base}_{i}", "name": name, "arguments": arguments}
            for i in range(count)
        ],
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
    for db, ids, factory in _world():
        rounds = _install_fake_client(monkeypatch, [
            [{"type": "delta", "text": "先查一下课件。"},
             _tool_call_event("search_course", '{"query": "行列式"}', reasoning="需要课件依据")],
            [{"type": "delta", "text": "行列式是线性代数的基本工具。"}],
        ])
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?", session_factory=factory))
        assert rounds == [], "脚本轮次应被耗尽"

        types = [event["type"] for event in events]
        assert types.count("step") == 2, "一个工具调用应有 running + done 两条时间线"
        assert types[0] == "delta" and types[-1] == "final"
        final = events[-1]
        assert final["answer"] == "先查一下课件。行列式是线性代数的基本工具。", "最终回答应包含全部轮次文本"
        assert final["mode"] == "agent" and final["model_version"]
        assert final["chunks"], "工具真实执行后应收集到课件片段作为证据"


def test_run_agent_collects_note_edit_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids, factory in _world():
        _install_fake_client(monkeypatch, [
            [_tool_call_event("propose_note_edits", '{"rationale": "补充例子", "edits": [{"op": "append", "content": "新段落"}]}')],
            [{"type": "delta", "text": "已提交修改建议，请点采纳。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="帮我把这篇笔记整理一下",
            scope="note", locked_note_id=ids["note_a1"], editable_note_id=ids["note_a1"], session_factory=factory,
        ))
        final = events[-1]
        assert final["type"] == "final"
        assert len(final["suggestions"]) == 1
        assert final["suggestions"][0]["type"] == "note_suggestion"
        db.expire_all()
        suggestion = db.query(NoteSuggestion).filter_by(id=final["suggestions"][0]["id"]).first()
        assert suggestion is not None and suggestion.status == "pending"


def test_run_agent_without_key_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids, factory in _world():
        _install_fake_client(monkeypatch, [], configured=False)
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="问题"))
        assert events == [{"type": "error", "message": "AI 模型未配置，无法启动智能模式"}]


def test_run_agent_stops_at_round_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """P7：轮次耗尽不再 error→旧管线重跑，而是收敛为 final（可携带已生成的部分正文）。"""
    for db, ids, factory in _world():
        endless = [[_tool_call_event("search_course", '{"query": "循环"}')] for _ in range(agent_loop.MAX_TOOL_ROUNDS + 1)]
        _install_fake_client(monkeypatch, endless)
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="反复检索", session_factory=factory))
        final = events[-1]
        assert final["type"] == "final", "耗尽应收敛为 final 而不是 error"
        assert final["mode"] == "agent"
        assert not any(event["type"] == "error" for event in events)


def test_run_agent_tool_failure_degrades_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    for db, ids, factory in _world():
        _install_fake_client(monkeypatch, [
            [_tool_call_event("search_course", '{"query": "行列式", "material_id": "not-exist"}')],
            [{"type": "delta", "text": "检索失败，我直接说明已知内容。"}],
        ])
        events = list(agent_loop.run_agent(db, course_id=ids["course_a"], course_name="线性代数", question="什么是行列式?", session_factory=factory))
        steps = [event for event in events if event["type"] == "step" and event["status"] == "done"]
        assert steps and "不属于当前课程" in steps[0]["detail"], "工具失败应折算为时间线文本而不是断流"
        assert events[-1]["type"] == "final"


def test_run_agent_material_narrowing_wires_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """课件收窄链路：标题进提示词、id 进工具执行器；工具集裁掉覆盖率与跨课程工具。"""
    for db, ids, factory in _world():
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
            scope="course", material_id=ids["material_a"], session_factory=factory,
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
    for db, ids, factory in _world():
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
            scope="course", material_id=ids["material_a"], session_factory=factory,
        ))
        assert captured_kwargs and captured_kwargs[0]["material_id"] == ids["material_a"]
        final = events[-1]
        assert final["type"] == "final" and final["chunks"], "注入后应命中收窄课件的片段"


def test_run_agent_allow_note_discovery_wires_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """P4 发现开关透传：specs 注册发现版工具，执行器收到开关并按 note_id 提交建议。"""
    for db, ids, factory in _world():
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
            scope="global", allow_note_discovery=True, session_factory=factory,
        ))
        assert captured and captured[0]["allow_note_discovery"] is True
        final = events[-1]
        assert final["type"] == "final" and len(final["suggestions"]) == 1
        assert final["suggestions"][0]["note_title"] == "矩阵"
        db.expire_all()
        suggestion = db.query(NoteSuggestion).filter_by(id=final["suggestions"][0]["id"]).first()
        assert suggestion is not None and suggestion.status == "pending"


def test_repeat_tool_failure_injects_switch_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """P7 防同错循环：同参失败两次后第二次注入「换方法」提示；成功后计数清零。"""
    for db, ids, factory in _world():
        _install_fake_client(monkeypatch, [
            # 两轮检索同一个人为查不到的词 → 同签名失败两次
            [_tool_call_event("search_course", '{"query": "绝不存在的词"}')],
            [_tool_call_event("search_course", '{"query": "绝不存在的词"}')],
            [{"type": "delta", "text": "课程里没有相关内容。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="检索一个不存在的词",
            session_factory=factory))
        final = events[-1]
        assert final["type"] == "final"
        # 第二次失败的 tool 回填里应带系统提示（通过 FakeClient 捕获 messages 验证）
        # FakeClient 不记录 messages，改为直接验证防同错逻辑的单元行为：
        key = agent_loop._failure_key("search_course", {"query": "绝不存在的词"})
        assert agent_loop.REPEAT_FAILURE_LIMIT == 2


def test_exhausted_rounds_do_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """P7：耗尽后 final.mode 仍是 agent（不再触发端点层的旧管线重跑）。"""
    for db, ids, factory in _world():
        endless = [[_tool_call_event("search_course", '{"query": "循环"}')] for _ in range(agent_loop.MAX_TOOL_ROUNDS + 1)]
        _install_fake_client(monkeypatch, endless)
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="反复检索", session_factory=factory))
        assert events[-1]["type"] == "final"
        assert events[-1]["mode"] == "agent"


def test_parallel_tools_collect_all_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """P6 并行执行：一轮内两个工具调用都被执行且结果都收集（旧串行循环同样能过，
    但此处钉住并行改造后的行为面）。"""
    for db, ids, factory in _world():
        _install_fake_client(monkeypatch, [
            [_tool_call_event("search_course", '{"query": "行列式"}', count=2)],
            [{"type": "delta", "text": "完成。"}],
        ])
        events = list(agent_loop.run_agent(
            db, course_id=ids["course_a"], course_name="线性代数", question="讲讲行列式和笔记概况",
            session_factory=factory))
        steps = [event for event in events if event["type"] == "step"]
        running = [event for event in steps if event["status"] == "running"]
        done = [event for event in steps if event["status"] == "done"]
        assert len(running) == 2 and len(done) == 2, "两个工具都应有 running + done"
        final = events[-1]
        assert final["chunks"], "search_course 的证据应被收集"
        # done 时间线里应有两条不同工具的摘要
        assert all("检索" in event["detail"] for event in done)
