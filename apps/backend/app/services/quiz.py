"""自测卷服务（v6 P10）：agent 出题、schema 硬门槛校验、作答判分。

设计要点（借鉴 OpenDesign 的硬门槛模式，见 docs/design v6 §3）：
- 模型产出的题目必须是可机器校验的 JSON schema——选择题 answer 必须在 options 里、
  选项数 ≥2、题干非空；不合格直接打回重出，绝不靠提示词求模型「拜托格式对一点」。
- 判分：选择题精确匹配（机器判）；简答题用 DeepSeek 对照标准答案与解释判分。
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.db.models import Course, Material, MaterialPage, Quiz, QuizAttempt, QuizItem, ReviewArtifact

QUIZ_MAX_ITEMS = 5
QUIZ_GENERATION_RETRIES = 2
QUIZ_PLAN_RETRIES = 1
QUIZ_ITEM_RETRIES = 1
QUIZ_SOURCE_MAX_CHARS = 6000
SHORT_ANSWER_MAX_CHARS = 500
DEFAULT_DIFFICULTY = "自适应"
# 依据判定窗口：解析里必须出现「素材原句」的至少这么长的连续片段（去空白后比较）
EVIDENCE_MIN_CHARS = 8
EVIDENCE_MAX_ITEMS = 8
# 选择题干扰项里的逃逸项：机器可判定的废题特征
ESCAPE_OPTION_MARKERS = (
    "以上都不对", "以上都对", "以上均不对", "以上均正确",
    "全部都不对", "全部都正确", "都不正确", "都正确",
)


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


QUIZ_PLAN_SYSTEM = """你是课程考点规划器。根据给定的课程材料规划可用于出题的考点，输出严格 JSON：
{"points": [{"point": "考点名（≤30字）", "evidence": "支撑该考点的材料原句（逐字摘录，8-80字）", "level": "basic|advanced|challenge"}]}

硬性要求：
1. evidence 必须逐字摘自材料，不得改写、不得概括（机器会拿它回查材料）；
2. 每个考点落在材料的不同位置，不要重复同一句话；
3. 按目标难度筛选：basic 考定义与记忆，advanced 考关系与应用，challenge 考推理与边界；
4. 只输出 JSON，不要围栏和解释。""".strip()

QUIZ_GENERATION_SYSTEM = """你是课程自测题出题器。根据给定的考点与材料出题，输出严格 JSON：
{"title": "卷子标题（≤60字）", "items": [{"point_index": 1, "type": "choice", "stem": "题干", "options": ["A选项文字", "B选项文字", "C选项文字", "D选项文字"], "answer": "正确选项的完整文字", "explanation": "为什么选它，必须引用材料原句"}, {"point_index": 2, "type": "short", "stem": "简答题干", "answer": "参考答案要点", "explanation": "判分要点，引用材料原句"}]}

硬性要求：
1. 每题对应考点清单里的一个 point_index，一题一个考点，不得重复；
2. 选择题的 answer 必须逐字等于 options 中的某一项（判分是机器精确匹配）；
3. explanation 必须包含该考点 evidence 的原句片段（连续至少 8 个字），这是机器校验项；
4. 干扰项必须来自材料相关内容，禁止「以上都不对」这类逃逸项；
5. 题干不得直接写出答案；
6. choice 与 short 混合；只输出 JSON，不要围栏和解释。""".strip()

QUIZ_ITEM_REPAIR_SYSTEM = """你是课程自测题出题器，正在返修一道未通过质量审查的题。
只输出 JSON：{"items": [一道题]}，题目结构同上；必须修正给出的失败原因，不得换考点。""".strip()


def _normalize(text: str) -> str:
    """去空白后比较：材料原句常被模型改动换行/空格，逐字比较会假阴性。"""
    return re.sub(r"\s+", "", text)


def _evidence_matches(explanation: str, evidence: str) -> bool:
    """解析里必须出现「素材原句」的至少 8 字连续片段，否则视为无法指认依据。"""
    exp = _normalize(explanation)
    ev = _normalize(evidence)
    if not ev:
        return False
    if len(ev) <= EVIDENCE_MIN_CHARS:
        return ev in exp
    return any(
        ev[index:index + EVIDENCE_MIN_CHARS] in exp
        for index in range(len(ev) - EVIDENCE_MIN_CHARS + 1)
    )


def validate_quiz_points(payload: Any, source: str, *, expected: int) -> list[dict[str, Any]]:
    """考点规划的硬门槛：依据必须逐字出现在素材里，重复/无依据的考点直接丢弃。"""
    if not isinstance(payload, dict):
        raise QuizSchemaError("考点规划顶层不是对象")
    raw_points = payload.get("points")
    if not isinstance(raw_points, list):
        raise QuizSchemaError("缺少 points 数组")
    source_norm = _normalize(source)
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_points:
        if not isinstance(entry, dict):
            continue
        point = str(entry.get("point") or "").strip()
        evidence = str(entry.get("evidence") or "").strip()
        if not point or not evidence or point in seen:
            continue
        if _normalize(evidence) not in source_norm:
            continue  # 依据回查不到 → 这个考点不可用
        seen.add(point)
        level = str(entry.get("level") or "").strip()
        if level not in ("basic", "advanced", "challenge"):
            level = ""
        points.append({"point": point[:120], "evidence": evidence[:200], "level": level})
    if not points:
        raise QuizSchemaError("没有可用考点：evidence 必须逐字摘自材料")
    return points[:max(1, expected)]


def plan_quiz_points(
    source: str, *, count: int, focus: str, difficulty: str, course_name: str
) -> list[dict[str, Any]]:
    """第一段：先规划考点，再出题——避免模型一上来就按材料开头编题。"""
    client = DeepSeekClient()
    if not client.configured:
        raise DeepSeekError("AI 模型未配置，无法出题")
    user = (
        f"课程：{course_name}\n"
        f"目标难度：{difficulty or DEFAULT_DIFFICULTY}\n"
        f"{f'出题重点：{focus}' if focus else ''}\n\n"
        f"课程材料：\n---\n{source}\n---\n\n"
        f"请规划 {count} 个考点（最多 {count + 2} 个）。"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": QUIZ_PLAN_SYSTEM},
        {"role": "user", "content": user},
    ]
    last_error: QuizSchemaError | None = None
    for _attempt in range(1, QUIZ_PLAN_RETRIES + 2):
        payload = client.complete_json(messages, max_tokens=1200)
        try:
            return validate_quiz_points(payload, source, expected=count + 2)
        except QuizSchemaError as exc:
            last_error = exc
            messages = messages + [
                {"role": "user", "content": f"你上一次的输出未通过校验：{exc}。请修正后重新输出完整 JSON。"},
            ]
    raise last_error or QuizSchemaError("考点规划未通过校验")


def review_quiz_item(item: dict[str, Any], point: dict[str, Any]) -> str | None:
    """第二段的机器质量审查：返回不合格原因，None 表示通过。不靠模型自查。"""
    stem = str(item.get("stem") or "")
    answer = str(item.get("answer") or "")
    explanation = str(item.get("explanation") or "")
    if item.get("type") == "choice":
        for option in item.get("options") or []:
            text = str(option)
            if any(marker in text for marker in ESCAPE_OPTION_MARKERS):
                return f"选项「{text[:20]}」是逃逸项，必须换成材料相关的干扰项"
        if len(answer) >= 4 and answer in stem:
            return "题干里直接包含了答案"
    if not _evidence_matches(explanation, str(point.get("evidence") or "")):
        return "解析没有引用材料原句，无法指认依据"
    return None


def _regenerate_item(
    client: DeepSeekClient,
    source: str,
    point: dict[str, Any],
    *,
    difficulty: str,
    course_name: str,
    reason: str,
) -> dict[str, Any] | None:
    """单题返修：把失败原因喂回去重出一题；仍不合格则返回 None（该考点放弃）。"""
    user = (
        f"课程：{course_name}\n目标难度：{difficulty or DEFAULT_DIFFICULTY}\n"
        f"考点：{point['point']}\n依据原句：{point['evidence']}\n"
        f"上一版未通过质量审查，原因：{reason}\n\n"
        f"课程材料：\n---\n{source}\n---\n\n只出 1 道题。"
    )
    try:
        payload = client.complete_json([
            {"role": "system", "content": QUIZ_GENERATION_SYSTEM},
            {"role": "user", "content": user},
        ], max_tokens=1200)
        candidate = (payload.get("items") or [None])[0] if isinstance(payload, dict) else None
        if not isinstance(candidate, dict):
            return None
        validated = validate_quiz_payload({"items": [candidate]}, expected_count=1)[0]
    except (QuizSchemaError, DeepSeekError, KeyError, IndexError, TypeError):
        return None
    if review_quiz_item(validated, point) is not None:
        return None
    return validated


def generate_quiz_from_points(
    source: str,
    points: list[dict[str, Any]],
    *,
    count: int,
    difficulty: str,
    course_name: str,
) -> dict[str, Any]:
    """第二段：按考点出题，逐题过质量审查；不合格单题返修一次，仍不合格则丢弃。"""
    client = DeepSeekClient()
    if not client.configured:
        raise DeepSeekError("AI 模型未配置，无法出题")
    point_lines = "\n".join(
        f"{index}. {point['point']}｜依据：{point['evidence']}"
        for index, point in enumerate(points, start=1)
    )
    target = min(count, len(points))
    user = (
        f"课程：{course_name}\n目标难度：{difficulty or DEFAULT_DIFFICULTY}\n\n"
        f"考点清单：\n{point_lines}\n\n"
        f"课程材料：\n---\n{source}\n---\n\n请出 {target} 道题。"
    )
    payload = client.complete_json([
        {"role": "system", "content": QUIZ_GENERATION_SYSTEM},
        {"role": "user", "content": user},
    ], max_tokens=3000)
    items = validate_quiz_payload(payload, expected_count=target)

    passed: list[dict[str, Any]] = []
    seen_points: set[str] = set()
    for item in items:
        index = item.get("point_index")
        point = points[index - 1] if isinstance(index, int) and 1 <= index <= len(points) else None
        if point is None or point["point"] in seen_points:
            continue
        reason = review_quiz_item(item, point)
        if reason is None:
            seen_points.add(point["point"])
            passed.append({**item, "difficulty": difficulty or DEFAULT_DIFFICULTY})
            continue
        repaired = _regenerate_item(
            client, source, point,
            difficulty=difficulty, course_name=course_name, reason=reason,
        )
        if repaired is not None:
            seen_points.add(point["point"])
            passed.append({**repaired, "difficulty": difficulty or DEFAULT_DIFFICULTY})
    title = str(payload.get("title") or f"{course_name}自测").strip()[:300]
    return {"title": title or f"{course_name}自测", "items": passed}


def generate_quiz_payload(
    source: str, *, count: int, focus: str, course_name: str, difficulty: str = ""
) -> dict[str, Any]:
    """两段式出题（v6 §7 第二批）：考点规划 → 出题并逐题机器质量审查。

    与旧版「单轮 + schema 重试」的差别：结构合法但内容废的题（无依据、逃逸项、
    题干泄答案）会被逐题挑出返修或丢弃，而不是照单全收。
    """
    points = plan_quiz_points(
        source, count=count, focus=focus, difficulty=difficulty, course_name=course_name,
    )
    result = generate_quiz_from_points(
        source, points, count=count, difficulty=difficulty, course_name=course_name,
    )
    if not result["items"]:
        raise QuizSchemaError("出的题没有通过质量审查，请换个重点或稍后再试")
    return result


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
            difficulty=str(item.get("difficulty") or DEFAULT_DIFFICULTY)[:30],
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
        points: list[dict[str, Any]] = []
        if item.item_type == "choice":
            correct = answer == item.answer
            rationale = "" if correct else f"正确答案是「{item.answer}」。"
        else:
            if not judge.configured:
                raise DeepSeekError("AI 模型未配置，简答题无法判分")
            verdict = judge.complete_json([
                {"role": "system", "content": "你是简答题判分器。对比学生答案与参考答案，输出 JSON：{\"correct\": true/false, \"comment\": \"一句话点评（指出参考答案的关键缺失）\", \"points\": [{\"point\": \"参考答案的一个关键要点\", \"hit\": true/false}]}。points 覆盖参考答案 2-5 个主要要点，hit 表示学生是否答到。学生答案覆盖核心要点即算对，表述不同不算错。"},
                {"role": "user", "content": f"题目：{item.stem}\n参考答案：{item.answer}\n判分要点：{item.explanation}\n学生答案：{answer}"},
            ], max_tokens=600)
            correct = bool(verdict.get("correct"))
            rationale = str(verdict.get("comment") or "")
            # B1 结构化判分：要点命中明细（模型可能不返回，按空处理，前端不依赖它才显示讲评）
            raw_points = verdict.get("points")
            if isinstance(raw_points, list):
                for entry in raw_points[:6]:
                    if not isinstance(entry, dict):
                        continue
                    point = str(entry.get("point") or "").strip()
                    if point:
                        points.append({"point": point[:160], "hit": bool(entry.get("hit"))})
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=item.id, answer=answer, correct=correct))
        results.append({
            "item_id": item.id, "seq": item.seq, "correct": correct,
            "answer": item.answer, "explanation": item.explanation, "comment": rationale,
            "points": points,
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
                    "difficulty": item.difficulty,
                    # 用户状态随题下发：答题卡的收藏/标记以库为真源初值（刷新后不回退）
                    "favorite": bool(item.favorite),
                    "marked": bool(item.marked),
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


def list_course_mistakes(db: Session, course_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """复习面板·题目数据源（v6 §7 学习闭环）：按题聚合历史作答与用户状态。

    - 入册规则：最近一次仍错，或被用户收藏/标记——掌握即可毕业，收藏的错题答对也不毕业；
    - dismissed（移出复习）的题不返回；favorite / marked / dismissed 随行下发；
    - 数据来自 quiz_attempts / quiz_items；favorite/marked/dismissed 为题目级用户状态。
    """
    rows = db.execute(
        select(QuizAttempt, QuizItem, Quiz, Material)
        .join(QuizItem, QuizItem.id == QuizAttempt.item_id)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .outerjoin(Material, Material.id == Quiz.material_id)
        .where(Quiz.course_id == course_id)
        .order_by(QuizAttempt.created_at.desc())
    ).all()

    latest: dict[str, tuple[QuizAttempt, QuizItem, Quiz, Material | None]] = {}
    wrong_counts: dict[str, int] = {}
    for attempt, item, quiz, material in rows:
        if item.id not in latest:
            latest[item.id] = (attempt, item, quiz, material)
        if not attempt.correct:
            wrong_counts[item.id] = wrong_counts.get(item.id, 0) + 1

    mistakes: list[dict[str, Any]] = []
    for item_id, (attempt, item, quiz, material) in latest.items():
        if item.dismissed:
            continue
        # 入册：最近一次仍错，或收藏/标记（收藏的题答对也不毕业）
        if attempt.correct and not item.favorite and not item.marked:
            continue
        mistakes.append({
            "item_id": item.id,
            "quiz_id": quiz.id,
            "quiz_title": quiz.title,
            "material_id": quiz.material_id,
            "material_title": material.lecture_title if material is not None else None,
            "seq": item.seq,
            "type": item.item_type,
            "stem": item.stem,
            "options": json.loads(item.options_json or "[]"),
            "answer": item.answer,
            "explanation": item.explanation,
            "difficulty": item.difficulty,
            "favorite": bool(item.favorite),
            "marked": bool(item.marked),
            "dismissed": bool(item.dismissed),
            "last_answer": attempt.answer,
            "last_at": attempt.created_at,
            "wrong_count": wrong_counts.get(item_id, 1),
        })
    mistakes.sort(key=lambda entry: entry["last_at"], reverse=True)
    return mistakes[:limit]


def get_quiz_for_client(db: Session, quiz_id: str) -> dict[str, Any] | None:
    """单卷直取（供答题卡按 id 精确补拉）：items 不带答案与解释，判分仍在服务端。"""
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        return None
    return {
        "id": quiz.id, "title": quiz.title, "status": quiz.status, "created_at": quiz.created_at,
        "items": [
            {
                "id": item.id, "seq": item.seq, "type": item.item_type, "stem": item.stem,
                "options": json.loads(item.options_json or "[]"),
                "difficulty": item.difficulty,
                "favorite": bool(item.favorite),
                "marked": bool(item.marked),
            }
            for item in quiz.items
        ],
    }


def set_quiz_item_flags(
    db: Session, item_id: str, *,
    favorite: bool | None = None, marked: bool | None = None, dismissed: bool | None = None,
) -> dict[str, Any] | None:
    """题目级用户状态（收藏/标记/移出复习）；只更新传入的字段。返回更新后的题目，不存在为 None。"""
    item = db.get(QuizItem, item_id)
    if item is None:
        return None
    if favorite is not None:
        item.favorite = favorite
    if marked is not None:
        item.marked = marked
    if dismissed is not None:
        item.dismissed = dismissed
    db.commit()
    db.refresh(item)
    return {
        "item_id": item.id, "favorite": bool(item.favorite),
        "marked": bool(item.marked), "dismissed": bool(item.dismissed),
    }


# ===== 复习产物（复习提纲 / 易混概念）跨会话存储（§7 学习闭环） =====

def create_review_artifact(
    db: Session, *, course_id: str, conversation_id: str | None,
    kind: str, title: str, payload: dict[str, Any],
) -> "ReviewArtifact":
    """技能产出即落库：复习面板跨会话可见，支持收藏与删除。"""
    import json as _json

    from app.db.model_utils import new_id

    artifact = ReviewArtifact(
        id=new_id(), course_id=course_id, conversation_id=conversation_id,
        kind=kind, title=title[:300], payload_json=_json.dumps(payload, ensure_ascii=False),
    )
    db.add(artifact)
    db.flush()
    return artifact


def list_review_artifacts(
    db: Session, course_id: str | None = None, kind: str | None = None, limit: int = 100,
    ids: list[str] | None = None, include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    """复习面板数据源：按创建时间倒序，返回解析后的负载与收藏状态。
    给了 ids 就按 id 精确取（技能卡挂载时回读真源用），忽略 course/kind；
    默认排除已移出复习（dismissed）的产物，面板的「已移出」区走 include_dismissed。"""
    import json as _json

    stmt = select(ReviewArtifact)
    if ids:
        stmt = stmt.where(ReviewArtifact.id.in_(ids))
    else:
        if not include_dismissed:
            stmt = stmt.where(ReviewArtifact.dismissed == False)  # noqa: E712
        if course_id:
            stmt = stmt.where(ReviewArtifact.course_id == course_id)
        if kind:
            stmt = stmt.where(ReviewArtifact.kind == kind)
    rows = list(db.scalars(stmt.order_by(ReviewArtifact.created_at.desc()).limit(limit)).all())
    result: list[dict[str, Any]] = []
    for artifact in rows:
        try:
            payload = _json.loads(artifact.payload_json)
        except ValueError:
            continue
        result.append({
            "id": artifact.id, "kind": artifact.kind, "title": artifact.title,
            "payload": payload, "favorite": bool(artifact.favorite),
            "dismissed": bool(artifact.dismissed),
            "created_at": artifact.created_at,
        })
    return result


def update_review_artifact(
    db: Session, artifact_id: str, *,
    favorite: bool | None = None, dismissed: bool | None = None,
) -> dict[str, Any] | None:
    """更新产物状态：收藏、移出复习（软移除，会话卡片与数据均保留，可恢复）。"""
    artifact = db.get(ReviewArtifact, artifact_id)
    if artifact is None:
        return None
    if favorite is not None:
        artifact.favorite = favorite
    if dismissed is not None:
        artifact.dismissed = dismissed
    db.commit()
    db.refresh(artifact)
    return {"id": artifact.id, "favorite": bool(artifact.favorite), "dismissed": bool(artifact.dismissed)}
