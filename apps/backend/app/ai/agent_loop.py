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
- 最多 ``MAX_TOOL_ROUNDS`` 轮，防止失控消耗。
"""

from __future__ import annotations

from collections.abc import Iterator
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
from app.ai.prompts import build_agent_messages
from app.core.config import settings
from app.retrieval.service import RetrievedChunk

MAX_TOOL_ROUNDS = 6


def _arg_summary(name: str, arguments: dict[str, Any]) -> str:
    """给时间线「执行中」一行用的参数摘要。"""
    if name == "search_course":
        return f"检索「{str(arguments.get('query') or '')[:30]}」"
    if name == "read_notebook":
        return "读取笔记正文"
    if name == "list_course_notebooks":
        return "浏览笔记列表"
    if name == "search_forest":
        return f"跨课程搜索「{str(arguments.get('query') or '')[:30]}」"
    if name == "get_source_coverage":
        return "检查资料引用覆盖"
    if name == "explain_term":
        return f"定位术语「{str(arguments.get('term') or '')[:20]}」"
    if name == "web_search":
        return f"联网搜索「{str(arguments.get('query') or '')[:30]}」"
    if name == "generate_quiz":
        return "生成课程自测题"
    if name == "generate_review_outline":
        return "整理复习提纲"
    if name == "generate_concept_contrast":
        return "辨析易混概念"
    if name == "propose_notebook_edits":
        return f"准备笔记修改建议：{str(arguments.get('rationale') or '')[:40]}"
    if name == "propose_knowledge_node":
        return f"提议知识节点「{str(arguments.get('candidate_name') or '')[:20]}」"
    return name


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
    locked_notebook_id: str | None = None,
    editable_notebook_id: str | None = None,
    reading_context: str = "",
    material_id: str | None = None,
    allow_web: bool = True,
    allow_quiz: bool = True,
    learning_goal: str | None = None,
    history: list[tuple[str, str]] | None = None,
    teacher_persona: str = DEFAULT_PERSONA_ID,
    conversation_id: str | None = None,
    learning_mode: str = "direct",
) -> Iterator[dict[str, Any]]:
    persona = resolve_persona(teacher_persona)
    teaching_context = infer_context(question, learning_goal)
    specs = build_tool_specs(
        scope=scope, editable_notebook=bool(editable_notebook_id),
        allow_web=allow_web, allow_quiz=allow_quiz,
        fixed_material_id=material_id,
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
    try:
        for _round in range(1, MAX_TOOL_ROUNDS + 1):
            round_text: list[str] = []
            tool_call_event: dict[str, Any] | None = None
            for event in client.chat_stream(messages, tools=specs, max_tokens=2400):
                if event["type"] == "reasoning":
                    # 思维链原文既不外发也不落库：只发一个不带内容的边界信号，供上层
                    # 计量思考耗时。模型侧要求的 reasoning_content 回传在 tool_calls
                    # 分支单独处理，不经过这里。
                    yield {"type": "thinking"}
                    continue
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

            for call in tool_call_event["tool_calls"]:
                arguments = arguments_from_json(call.get("arguments", ""))
                yield {
                    "type": "step",
                    "tool": call["name"],
                    "detail": _arg_summary(call["name"], arguments),
                    "status": "running",
                }
                outcome = execute_tool(
                    db,
                    course_id=course_id,
                    name=call["name"],
                    arguments=arguments,
                    scope=scope,
                    locked_notebook_id=locked_notebook_id,
                    editable_notebook_id=editable_notebook_id,
                    allow_web=allow_web,
                    allow_quiz=allow_quiz,
                    conversation_id=conversation_id,
                    fixed_material_id=material_id,
                )
                collected_chunks.extend(outcome.chunks)
                collected_web.extend(outcome.web_results)
                collected_suggestions.extend(outcome.suggestions)
                yield {
                    "type": "step",
                    "tool": call["name"],
                    "detail": outcome.summary,
                    "status": "done",
                    "suggestions": outcome.suggestions,
                }
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": outcome.payload_text,
                })
        yield {"type": "error", "message": f"工具调用轮次达到上限（{MAX_TOOL_ROUNDS} 轮），已停止执行"}
    except DeepSeekError as exc:
        yield {"type": "error", "message": str(exc)}
