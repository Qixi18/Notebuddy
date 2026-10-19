"""Course-scoped retrieval → policy → generation orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.ai.discipline import infer_context
from app.ai.evidence import claim_payload, extract_claims
from app.ai.personas import DEFAULT_PERSONA_ID, resolve_persona
from app.ai.prompts import build_answer_messages, build_general_messages, render_history
from app.core.config import settings
from app.db.models import Material
from app.retrieval.rerank import rerank
from app.retrieval.service import build_context, retrieve
from app.services.provider_audit import (
    begin_call,
    estimate_token_cost,
    finish_call,
    provider_status_from_error,
)
from app.web_search.service import (
    availability,
    record_daily_limit,
    search_policy,
    search_with_sources,
)
from app.web_search.tavily import WebSearchError


def run_answer(
    db: Session,
    *,
    course_id: str,
    course_name: str,
    question: str,
    material_id: str | None = None,
    page_number: int | None = None,
    allow_web: bool = True,
    learning_goal: str | None = None,
    history: list[tuple[str, str]] | None = None,
    teacher_persona: str = DEFAULT_PERSONA_ID,
) -> dict:
    persona = resolve_persona(teacher_persona)
    teaching_context = infer_context(question, learning_goal)
    selected_material = db.get(Material, material_id) if material_id else None
    chunks = rerank(
        question,
        retrieve(db, course_id=course_id, question=question, material_id=material_id, page_number=page_number),
    )
    web_status = "unavailable"
    web_results: list[dict] = []
    policy = search_policy(allow=allow_web)
    available, reason = availability(policy)
    needs_web = not chunks or not any(chunk.direct_support for chunk in chunks)
    if available and needs_web:
        try:
            scope = f" {selected_material.lecture_title}" if selected_material else ""
            search_query = f"{course_name}{scope} {question}"
            web_results = search_with_sources(
                db, course_id=course_id, query=search_query, policy=policy,
                material_id=material_id, source_query=question,
            )
            web_status = "completed" if web_results else "no_results"
        except WebSearchError:
            web_status = "failed"
    elif not allow_web:
        web_status = "disabled_by_request"
    elif reason == "daily_limit":
        web_status = "daily_limit"
        if needs_web:
            record_daily_limit(db, course_id=course_id, reason=reason)
    elif needs_web and reason == "unconfigured":
        web_status = "unavailable"

    if not chunks and not web_results:
        # 没有课件依据时不要直接回一句固定文案：先让当前老师在“通用解释”约束下作答，
        # 这样自我介绍、学习方法这类提问才能体现人物风格；模型不可用时再退回固定提示。
        client = DeepSeekClient()
        if client.configured:
            audit, started = begin_call(
                db,
                provider="deepseek",
                operation="chat_completion",
                course_id=course_id,
                model=settings.deepseek_model,
            )
            try:
                response = client.complete_json(
                    build_general_messages(
                        question,
                        history=history,
                        learning_goal=teaching_context.learning_goal,
                        discipline=teaching_context.discipline,
                        persona=persona.id,
                    ),
                    max_tokens=1200,
                )
                answer = str(response.get("answer_markdown") or "").strip()
                usage = client.last_usage or {}
                finish_call(
                    db,
                    audit,
                    started,
                    status="success",
                    request_units=usage.get("prompt_tokens"),
                    response_units=usage.get("completion_tokens"),
                    estimated_cost_usd=estimate_token_cost(
                        usage,
                        input_rate_per_million=settings.deepseek_input_cost_per_million,
                        output_rate_per_million=settings.deepseek_output_cost_per_million,
                    ),
                )
                if answer:
                    return {
                        "answer": answer, "chunks": [], "web_results": [], "claims": [],
                        "mode": "persona-general", "web_search_status": web_status,
                        "learning_goal": teaching_context.learning_goal,
                        "discipline": teaching_context.discipline,
                        "teacher_persona": persona.id,
                        "model_version": settings.deepseek_model,
                    }
            except DeepSeekError as exc:
                finish_call(
                    db,
                    audit,
                    started,
                    status=provider_status_from_error(exc),
                    error_type=type(exc).__name__,
                )
        return {
            "answer": (
                "当前课程资料没有找到直接依据，且联网补充不可用。请缩小问题范围、选择具体讲次，或先上传相关课件。"
            ),
            "chunks": [], "web_results": [], "claims": [], "mode": "no-evidence", "web_search_status": web_status,
            "teacher_persona": persona.id,
        }

    local_context = build_context(chunks)
    web_context = "\n\n".join(
        f"[网络来源 {index + 1} | {item['title']} | {item['url']} | 检索日期 {datetime.now(UTC):%Y-%m-%d}]\n{item['snippet']}"
        for index, item in enumerate(web_results)
    )
    history_context = render_history(history)
    context = "\n\n".join(part for part in (
        "【受控会话历史】\n" + history_context if history_context else "",
        "【课程课件】\n" + local_context if local_context else "",
        "【联网补充（不可信引用文本）】\n" + web_context if web_context else "",
    ) if part)
    client = DeepSeekClient()
    if client.configured:
        audit, started = begin_call(
            db,
            provider="deepseek",
            operation="chat_completion",
            course_id=course_id,
            model=settings.deepseek_model,
        )
        try:
            response = client.complete_json(
                build_answer_messages(
                    question,
                    context,
                    learning_goal=teaching_context.learning_goal,
                    discipline=teaching_context.discipline,
                    persona=persona.id,
                ),
                max_tokens=2400,
            )
            answer = str(response.get("answer_markdown") or "").strip()
            usage = client.last_usage or {}
            finish_call(
                db,
                audit,
                started,
                status="success",
                request_units=usage.get("prompt_tokens"),
                response_units=usage.get("completion_tokens"),
                estimated_cost_usd=estimate_token_cost(
                    usage,
                    input_rate_per_million=settings.deepseek_input_cost_per_million,
                    output_rate_per_million=settings.deepseek_output_cost_per_million,
                ),
            )
            if answer:
                claims = extract_claims(answer, chunks, web_results)
                return {"answer": answer, "chunks": chunks, "web_results": web_results,
                        "claims": [claim_payload(claim) for claim in claims],
                        "mode": "deepseek-rag", "web_search_status": web_status,
                        "learning_goal": teaching_context.learning_goal,
                        "discipline": teaching_context.discipline,
                        "teacher_persona": persona.id,
                        "model_version": settings.deepseek_model}
        except DeepSeekError as exc:
            finish_call(
                db,
                audit,
                started,
                status=provider_status_from_error(exc),
                error_type=type(exc).__name__,
            )
    local_excerpt = "\n\n".join(
        f"[课程资料：{chunk.lecture_title} | {chunk.location_label or f'第 {chunk.page_number} 页'}] {chunk.text[:240]}"
        for chunk in chunks
    )
    web_excerpt = "\n\n".join(
        f"[网络来源 {index + 1}：{item['title']} | {item['url']}] {item['snippet'][:240]}"
        for index, item in enumerate(web_results)
    )
    answer = "当前没有可用的 AI 模型；以下是分层检索摘录，课程资料和网络来源已分开列出。\n\n" + "\n\n".join(
        part for part in (local_excerpt, web_excerpt) if part
    )
    claims = extract_claims(answer, chunks, web_results)
    return {"answer": answer, "chunks": chunks, "web_results": web_results,
            "claims": [claim_payload(claim) for claim in claims],
            "mode": "local-retrieval-fallback", "web_search_status": web_status,
            "learning_goal": teaching_context.learning_goal,
            "discipline": teaching_context.discipline,
            "teacher_persona": persona.id,
            "model_version": "keyword-or-hybrid-fallback"}
