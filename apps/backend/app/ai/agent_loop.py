"""Agent 循环：多轮工具调用 + 流式事件产出（悬浮坞 agent 化的核心）。

每次调用产出的事件流（经 SSE 转发给前端）：
- ``{"type": "step", "tool", "detail", "status": "running"|"done"}`` 工具执行时间线；
- ``{"type": "delta", "text"}`` 回答文本增量（可直接渲染）；
- ``{"type": "final", "answer", "sources", "suggestions", "mode", "model_version", ...}``
  收尾事件，携带证据与建议；
- ``{"type": "error", "message"}`` 失败事件，由 API 层回退旧问答管线。

安全设计：
- 思考模型的思维链不外发（只内部回填），前端仅有 busy 指示；
- 每轮都携带完整工具集（思考模型在缺少 tools 时会把工具调用内联成文本）；
- 工具失败折算为文本回给模型继续，绝不中断流；
- 最多 ``MAX_TOOL_ROUNDS`` 轮：倒数第二轮注入收敛提示，耗尽后基于已收集证据
  直接收尾作答（不再整段回退旧管线重跑——v6 P7）；
- 同一工具+同参连续失败 2 次注入确定性提示，防止模型原地打转（v6 P7）；
- 一轮内多个工具调用并行执行且各带超时（v6 P6），检索类不再串行等待。
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from sqlalchemy.orm import Session

from app.ai.agent_tools import (
    AgentScope,
    arguments_from_json,
    build_tool_specs,
    execute_tool,
)
from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.ai.discipline import infer_context
from app.ai.personas import DEFAULT_PERSONA_ID, resolve_persona
from app.ai.prompts import build_agent_messages, build_answer_messages
from app.core.config import settings
from app.db.models import Material
from app.retrieval.service import RetrievedChunk

MAX_TOOL_ROUNDS = 6
# 每个工具的执行超时（秒）：检索/读取类快，联网与写入类放宽（v6 P6）
TOOL_TIMEOUT_SECONDS = 30
# 同一工具+同参连续失败达到该次数后注入确定性提示（v6 P7）
REPEAT_FAILURE_LIMIT = 2
# 工具执行线程池上限：一轮内的工具调用数不会超过这个量级
_TOOL_WORKERS = 4


def _tool_timeout(name: str) -> int:
    """联网检索比库内工具慢；写工具涉及提交建议，也放宽一档。"""
    if name == "web_search":
        return 40
    if name.startswith("propose_"):
        return 30
    return TOOL_TIMEOUT_SECONDS


def _arg_summary(name: str, arguments: dict[str, Any]) -> str:
    """给时间线「执行中」一行用的参数摘要。"""
    if name == "search_course":
        return f"检索「{str(arguments.get('query') or '')[:30]}」"
    if name == "read_note":
        return "读取笔记正文"
    if name == "list_course_notes":
        return "浏览笔记列表"
    if name == "list_course_materials":
        return "浏览课件清单"
    if name == "read_material_page":
        return f"读取课件第 {arguments.get('page_number')} 页"
    if name == "search_forest":
        return f"跨课程搜索「{str(arguments.get('query') or '')[:30]}」"
    if name == "get_note_coverage":
        return "检查课件覆盖"
    if name == "explain_term":
        return f"定位术语「{str(arguments.get('term') or '')[:20]}」"
    if name == "web_search":
        return f"联网搜索「{str(arguments.get('query') or '')[:30]}」"
    if name == "propose_note_edits":
        return f"准备笔记修改建议：{str(arguments.get('rationale') or '')[:40]}"
    if name == "propose_knowledge_node":
        return f"提议知识节点「{str(arguments.get('candidate_name') or '')[:20]}」"
    return name


def _failure_key(name: str, arguments: dict[str, Any]) -> str:
    """工具失败签名：同名工具的关键参数相同视为同一失败（v6 P7 防同错循环）。"""
    if name == "search_course":
        return f"{name}:{str(arguments.get('query') or '')[:60]}:{arguments.get('material_id') or ''}"
    if name in ("read_note", "propose_note_edits"):
        return f"{name}:{arguments.get('note_id') or ''}"
    if name in ("read_material_page", "get_note_coverage"):
        return f"{name}:{arguments.get('material_id') or ''}:{arguments.get('page_number') or ''}"
    return f"{name}:{str(arguments)[:80]}"


def _dedupe_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: set[str] = set()
    unique: list[RetrievedChunk] = []
    for chunk in chunks:
        key = chunk.source_ref_id or chunk.page_block_id or f"{chunk.material_id}:{chunk.page_number}:{hash(chunk.text)}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return unique


def run_agent(
    db: Session,
    *,
    course_id: str,
    course_name: str,
    question: str,
    scope: AgentScope = "course",
    locked_note_id: str | None = None,
    editable_note_id: str | None = None,
    reading_context: str = "",
    material_id: str | None = None,
    allow_web: bool = True,
    learning_goal: str | None = None,
    history: list[tuple[str, str]] | None = None,
    teacher_persona: str = DEFAULT_PERSONA_ID,
    allow_note_discovery: bool = False,
    allow_quiz: bool = False,
    learning_mode: str = "direct",
    conversation_id: str | None = None,
    session_factory: Any | None = None,
) -> Iterator[dict[str, Any]]:
    persona = resolve_persona(teacher_persona)
    teaching_context = infer_context(question, learning_goal)
    # 课件收窄（消息级）：标题进提示词，id 进工具装配与执行器（注入 + 拒覆盖）。
    material_title: str | None = None
    if material_id:
        material = db.get(Material, material_id)
        if material is not None:
            material_title = material.lecture_title
    specs = build_tool_specs(
        scope=scope, editable_note=bool(editable_note_id), allow_web=allow_web,
        material_id=material_id, allow_note_discovery=allow_note_discovery,
        allow_quiz=allow_quiz,
    )
    messages = build_agent_messages(
        question,
        course_name=course_name,
        scope=scope,
        learning_goal=teaching_context.learning_goal,
        discipline=teaching_context.discipline,
        persona=persona.id,
        history=history,
        reading_context=reading_context,
        material_title=material_title,
        allow_note_discovery=allow_note_discovery,
        learning_mode=learning_mode,
    )
    client = DeepSeekClient()
    if not client.configured:
        yield {"type": "error", "message": "AI 模型未配置，无法启动智能模式"}
        return

    collected_chunks: list[RetrievedChunk] = []
    collected_web: list[dict] = []
    collected_suggestions: list[dict] = []
    total_text: list[str] = []
    failure_counts: dict[str, int] = {}
    warned_failures: set[str] = set()
    try:
        for round_index in range(1, MAX_TOOL_ROUNDS + 1):
            round_text: list[str] = []
            tool_call_event: dict[str, Any] | None = None
            for event in client.chat_stream(messages, tools=specs, max_tokens=2400):
                if event["type"] == "reasoning":
                    continue  # 思维链不外发，仅在结束事件中带回用于回填
                if event["type"] == "delta":
                    round_text.append(event["text"])
                    total_text.append(event["text"])
                    yield event
                else:
                    tool_call_event = event
            if tool_call_event is None:
                yield {
                    "type": "final",
                    "answer": "".join(total_text).strip(),
                    "mode": "agent",
                    "model_version": settings.deepseek_model,
                    "chunks": _dedupe_chunks(collected_chunks),
                    "web_results": collected_web,
                    "suggestions": collected_suggestions,
                    "learning_goal": teaching_context.learning_goal,
                    "discipline": teaching_context.discipline,
                    "teacher_persona": persona.id,
                    "web_search_status": "tool_driven",
                }
                return

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(round_text).strip() or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in tool_call_event["tool_calls"]
                ],
            }
            if tool_call_event.get("reasoning_content"):
                # 思考模式硬性要求：回传上一轮思维链，否则下一轮请求报 400
                assistant_message["reasoning_content"] = tool_call_event["reasoning_content"]
            messages.append(assistant_message)

            # 一轮内的多个工具调用并行执行（v6 P6）：总耗时 ≈ 最慢一个而非相加。
            # SQLAlchemy Session 非线程安全 → 每个工具用独立 Session；
            # 工具失败折算文本回模型，超时同样降级为文本，绝不打断流。
            calls = tool_call_event["tool_calls"]
            for call in calls:
                yield {
                    "type": "step",
                    "tool": call["name"],
                    "detail": _arg_summary(call["name"], arguments_from_json(call.get("arguments", ""))),
                    "status": "running",
                }

            tool_session_factory = session_factory
            if tool_session_factory is None:
                from app.db.database import SessionLocal
                tool_session_factory = SessionLocal

            def run_one(call: dict[str, Any]) -> tuple[dict[str, Any], Any, bool]:
                """在独立 Session 里执行单个工具；返回 (call, outcome, timed_out)。

                写工具内部（如 create_note_suggestion）只 flush 不 commit——提交历来由
                端点层负责，而这里的 Session 是本函数私有的，with 退出即回滚未提交内容，
                所以执行成功后必须在此显式 commit，否则建议类产出会静默丢失。
                """
                arguments = arguments_from_json(call.get("arguments", ""))
                with tool_session_factory() as tool_db:
                    outcome = execute_tool(
                        tool_db,
                        course_id=course_id,
                        name=call["name"],
                        arguments=arguments,
                        scope=scope,
                        locked_note_id=locked_note_id,
                        editable_note_id=editable_note_id,
                        allow_web=allow_web,
                        material_id=material_id,
                        allow_note_discovery=allow_note_discovery,
                        allow_quiz=allow_quiz,
                        conversation_id=conversation_id,
                    )
                    tool_db.commit()
                return call, outcome, False

            timed_out_calls: set[str] = set()
            with ThreadPoolExecutor(max_workers=_TOOL_WORKERS) as pool:
                futures = {pool.submit(run_one, call): call for call in calls}
                results: list[tuple[dict[str, Any], Any, bool]] = []
                for future, call in futures.items():
                    try:
                        results.append(future.result(timeout=_tool_timeout(call["name"])))
                    except FutureTimeoutError:
                        future.cancel()
                        timed_out_calls.add(call["id"])
                        results.append((call, None, True))

            for call, outcome, timed_out in results:
                arguments = arguments_from_json(call.get("arguments", ""))
                if timed_out or outcome is None:
                    timeout_note = (
                        f"工具 {call['name']} 执行超时（{_tool_timeout(call['name'])} 秒）。"
                        "请换一种方式继续，或如实告知用户该步骤未完成。"
                    )
                    failure_key = _failure_key(call["name"], arguments)
                    failure_counts[failure_key] = failure_counts.get(failure_key, 0) + 1
                    yield {
                        "type": "step",
                        "tool": call["name"],
                        "detail": "执行超时",
                        "status": "done",
                    }
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": timeout_note})
                    continue

                collected_chunks.extend(outcome.chunks)
                collected_web.extend(outcome.web_results)
                collected_suggestions.extend(outcome.suggestions)
                # 防同错循环（v6 P7）：同一签名反复失败时，注入确定性提示让模型换方法
                failed = "失败" in outcome.summary or "拒绝" in outcome.summary or "错误" in outcome.summary
                failure_key = _failure_key(call["name"], arguments)
                if failed:
                    failure_counts[failure_key] = failure_counts.get(failure_key, 0) + 1
                else:
                    failure_counts.pop(failure_key, None)
                    warned_failures.discard(failure_key)
                extra = ""
                if failed and failure_counts[failure_key] >= REPEAT_FAILURE_LIMIT and failure_key not in warned_failures:
                    warned_failures.add(failure_key)
                    extra = (
                        f"\n（系统提示：{call['name']} 以相同参数已失败 {failure_counts[failure_key]} 次。"
                        "请换一种方法或直接基于已有信息作答，不要再用相同参数重试。）"
                    )
                yield {
                    "type": "step",
                    "tool": call["name"],
                    "detail": outcome.summary,
                    "status": "done",
                }
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": outcome.payload_text + extra})

            # 轮次预算（v6 P7）：倒数第二轮后注入收敛提示，让模型最后一轮直接作答而非被硬截断
            if round_index == MAX_TOOL_ROUNDS - 1:
                messages.append({
                    "role": "user",
                    "content": "（系统提示：这是最后一轮工具调用机会，下一轮请直接给出最终回答，不要再调用工具。）",
                })
        # 轮次耗尽（v6 P7）：不再走 error → 旧管线整段重跑（丢正文、双倍时延费用），
        # 改为基于已收集的证据直接收尾作答一次
        yield {
            "type": "final",
            "answer": "".join(total_text).strip(),
            "mode": "agent",
            "model_version": settings.deepseek_model,
            "chunks": _dedupe_chunks(collected_chunks),
            "web_results": collected_web,
            "suggestions": collected_suggestions,
            "learning_goal": teaching_context.learning_goal,
            "discipline": teaching_context.discipline,
            "teacher_persona": persona.id,
            "web_search_status": "tool_driven",
        }
    except DeepSeekError as exc:
        yield {"type": "error", "message": str(exc)}
