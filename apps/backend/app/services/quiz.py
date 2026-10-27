"""自测卷服务（v6 P10）：agent 出题、schema 硬门槛校验、作答判分。

设计要点（借鉴 OpenDesign 的硬门槛模式，见 docs/design v6 §3）：
- 模型产出的题目必须是可机器校验的 JSON schema——选择题 answer 必须在 options 里、
  选项数 ≥2、题干非空；不合格直接打回重出，绝不靠提示词求模型「拜托格式对一点」。
- 判分：选择题精确匹配（机器判）；简答题用 DeepSeek 对照标准答案与解释判分。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.models import Course, Material, MaterialPage, Quiz, QuizAttempt, QuizItem

QUIZ_MAX_ITEMS = 5
QUIZ_GENERATION_RETRIES = 2
QUIZ_SOURCE_MAX_CHARS = 6000
SHORT_ANSWER_MAX_CHARS = 500


class QuizSchemaError(ValueError):
    """模型产出的题目不符合 schema——硬门槛不通过。"""


def validate_quiz_payload(payload: Any, *, expected_count: int) -> list[dict[str, Any]]:
    """硬门槛：题目数组和每一道题都必须合规，任何一条不满足即抛 QuizSchemaError。"""
    if not isinstance(payload, dict):
        raise QuizSchemaError("顶层不是对象")
    items = payload.get("items")
    if not isinstance(items, list):
        raise QuizSchemaError("缺少 items 数组")
    if not 1 <= len(items) <= expected_count:
        raise QuizSchemaError(f"题目数量应为 1-{expected_count}，实际 {len(items)}")
    seen_stems: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise QuizSchemaError(f"第 {index} 题不是对象")
        stem = str(item.get("stem") or "").strip()
        if not stem:
            raise QuizSchemaError(f"第 {index} 题题干为空")
        if stem in seen_stems:
            raise QuizSchemaError(f"第 {index} 题与前面的题重复")
        seen_stems.add(stem)
        item_type = str(item.get("type") or "choice")
        if item_type not in ("choice", "short"):
            raise QuizSchemaError(f"第 {index} 题类型必须是 choice/short")
        answer = str(item.get("answer") or "").strip()
        if not answer:
            raise QuizSchemaError(f"第 {index} 题缺少答案")
        if item_type == "choice":
            options = item.get("options")
            if not isinstance(options, list) or len(options) < 2:
                raise QuizSchemaError(f"第 {index} 题选择题至少 2 个选项")
            options = [str(option).strip() for option in options if str(option).strip()]
            if len(options) < 2:
                raise QuizSchemaError(f"第 {index} 题选项全为空")
            if answer not in options:
                raise QuizSchemaError(f"第 {index} 题答案不在选项中（硬门槛：answer 必须逐字等于某个 option）")
            item["options"] = options
        else:
            item["options"] = []
        item["type"] = item_type
        item["explanation"] = str(item.get("explanation") or "").strip()
    return items


def _quiz_source(db: Session, *, course_id: str, material_id: str | None, note_markdown: str) -> str:
    """出题素材：笔记正文优先，其次收窄课件的原文页拼合；
    两者都没有时回退到课程小节笔记——「考考我」不该因为没选课件就哑火。"""
    if note_markdown.strip():
        return note_markdown[:QUIZ_SOURCE_MAX_CHARS]
    if material_id:
        material = db.get(Material, material_id)
        if material is not None and material.course_id == course_id and material.deleted_at is None:
            pages = list(db.scalars(
                select(MaterialPage)
                .where(MaterialPage.material_id == material_id, MaterialPage.parse_status == "parsed")
                .order_by(MaterialPage.page_number)
                .limit(6)
            ).all())
            parts: list[str] = []
            used = 0
            for page in pages:
                text = f"【第 {page.page_number} 页】{page.raw_text or ''}".strip()
                if used + len(text) > QUIZ_SOURCE_MAX_CHARS:
                    break
                parts.append(text)
                used += len(text)
            if parts:
                return "\n\n".join(parts)
    from app.services.skills import _skill_source

    return _skill_source(db, course_id=course_id, material_id=None, note_id=None)


QUIZ_GENERATION_SYSTEM = """你是课程自测题出题器。根据给定的课程材料出题，输出严格 JSON：
{"title": "卷子标题（≤60字）", "items": [{"type": "choice", "stem": "题干", "options": ["A选项文字", "B选项文字", "C选项文字", "D选项文字"], "answer": "正确选项的完整文字", "explanation": "为什么选它，引用材料原话"}, {"type": "short", "stem": "简答题干", "answer": "参考答案要点", "explanation": "判分要点"}]}

硬性要求：
1. 选择题的 answer 必须逐字等于 options 中的某一项（判分是机器精确匹配）。
2. choice 与 short 混合；至少一半是 choice。
3. 只考材料里有依据的内容，explanation 引用材料原话；不要出材料外或常识题。
4. 只输出 JSON，不要围栏和解释。""".strip()


def generate_quiz_payload(
    source: str, *, count: int, focus: str, course_name: str
) -> dict[str, Any]:
    """调模型出题并过 schema 硬门槛；不合格带原因重试（critique 轮），仍不合格抛错。"""
    client = DeepSeekClient()
    if not client.configured:
        raise DeepSeekError("AI 模型未配置，无法出题")
    user = f"课程：{course_name}\n{f'出题重点：{focus}' if focus else ''}\n\n课程材料：\n---\n{source}\n---\n\n请出 {count} 道题。"
    messages: list[dict[str, str]] = [
        {"role": "system", "content": QUIZ_GENERATION_SYSTEM},
        {"role": "user", "content": user},
    ]
    last_error: QuizSchemaError | None = None
    for _attempt in range(1, QUIZ_GENERATION_RETRIES + 1):
        payload = client.complete_json(messages, max_tokens=3000)
        try:
            items = validate_quiz_payload(payload, expected_count=count)
        except QuizSchemaError as exc:
            last_error = exc
            # critique 轮（借鉴 OpenDesign plan→generate→critique）：把上一轮的
            # 具体不合格原因喂回去，让模型修正而不是盲重试
            messages = messages + [{"role": "user", "content": f"你上一次的输出未通过校验：{exc}。请修正后重新输出完整 JSON。"}]
            continue
        return {"title": str(payload.get("title") or "课程自测")[:300], "items": items}
    raise last_error or QuizSchemaError("出题未通过校验")


def create_quiz(
    db: Session,
    *,
    course_id: str,
    conversation_id: str | None,
    material_id: str | None,
    title: str,
    items: list[dict[str, Any]],
) -> Quiz:
    quiz = Quiz(
        course_id=course_id, conversation_id=conversation_id, material_id=material_id,
        title=title, status="active",
    )
    db.add(quiz)
    db.flush()
    for seq, item in enumerate(items, start=1):
        db.add(QuizItem(
            quiz_id=quiz.id, seq=seq, item_type=item["type"], stem=item["stem"],
            options_json=json.dumps(item.get("options") or [], ensure_ascii=False),
            answer=item["answer"], explanation=item.get("explanation") or "",
        ))
    db.flush()
    return quiz


def grade_answers(
    db: Session, quiz: Quiz, answers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """判分并落 attempts：choice 精确匹配；short 交模型对照参考答案判。"""
    items = {item.id: item for item in quiz.items}
    results: list[dict[str, Any]] = []
    judge = DeepSeekClient()
    for entry in answers:
        item = items.get(str(entry.get("item_id") or ""))
        if item is None:
            continue
        answer = str(entry.get("answer") or "").strip()[:SHORT_ANSWER_MAX_CHARS]
        if not answer:
            continue
        if item.item_type == "choice":
            correct = answer == item.answer
            rationale = "" if correct else f"正确答案是「{item.answer}」。"
        else:
            if not judge.configured:
                raise DeepSeekError("AI 模型未配置，简答题无法判分")
            verdict = judge.complete_json([
                {"role": "system", "content": "你是简答题判分器。对比学生答案与参考答案，输出 JSON：{\"correct\": true/false, \"comment\": \"一句话点评（指出参考答案的关键缺失）\"}。学生答案覆盖参考答案的核心要点即算对，表述不同不算错。"},
                {"role": "user", "content": f"题目：{item.stem}\n参考答案：{item.answer}\n判分要点：{item.explanation}\n学生答案：{answer}"},
            ], max_tokens=500)
            correct = bool(verdict.get("correct"))
            rationale = str(verdict.get("comment") or "")
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=item.id, answer=answer, correct=correct))
        results.append({
            "item_id": item.id, "seq": item.seq, "correct": correct,
            "answer": item.answer, "explanation": item.explanation, "comment": rationale,
        })
    db.flush()
    # 全部题目都有作答记录 → 卷子完成
    attempted = set(db.scalars(
        select(QuizAttempt.item_id).where(QuizAttempt.quiz_id == quiz.id)
    ).all())
    if all(item.id in attempted for item in quiz.items):
        quiz.status = "completed"
    db.flush()
    return results


def list_course_quizzes(db: Session, course_id: str, status: str) -> list[dict[str, Any]]:
    quizzes = list(db.scalars(
        select(Quiz)
        .where(Quiz.course_id == course_id, Quiz.status == status)
        .options(selectinload(Quiz.items))
        .order_by(Quiz.created_at.desc())
        .limit(10)
    ).all())
    return [
        {
            "id": quiz.id, "title": quiz.title, "status": quiz.status, "created_at": quiz.created_at,
            "items": [
                {
                    "id": item.id, "seq": item.seq, "type": item.item_type, "stem": item.stem,
                    "options": json.loads(item.options_json or "[]"),
                    # 答案与解释不下发——判分在服务端，防止前端偷看
                }
                for item in quiz.items
            ],
        }
        for quiz in quizzes
    ]


def ensure_course_for_quiz(db: Session, course_id: str) -> None:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
