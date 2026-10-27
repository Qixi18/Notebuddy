"""自测卷测试（v6 P10）：schema 硬门槛、出题工具、判分。"""

from __future__ import annotations

import pytest

from app.services.quiz import (
    QuizSchemaError,
    create_quiz,
    grade_answers,
    validate_quiz_payload,
)


def _valid_payload() -> dict:
    return {
        "title": "行列式小测",
        "items": [
            {
                "type": "choice", "stem": "行列式为 0 说明什么？",
                "options": ["矩阵可逆", "矩阵不可逆", "矩阵是单位阵", "矩阵是对称阵"],
                "answer": "矩阵不可逆", "explanation": "材料：行列式为零等价于矩阵不可逆。",
            },
            {
                "type": "short", "stem": "用一句话说明行列式的几何意义。",
                "answer": "行向量张成的平行多面体体积（缩放因子）",
                "explanation": "答案要点：体积/缩放因子。",
            },
        ],
    }


def test_validate_quiz_payload_accepts_wellformed() -> None:
    items = validate_quiz_payload(_valid_payload(), expected_count=5)
    assert len(items) == 2
    assert items[0]["type"] == "choice" and items[0]["answer"] == "矩阵不可逆"


def test_validate_quiz_payload_hard_gates() -> None:
    """硬门槛：答案不在选项中 / 选项不足 / 空题干 / 重复题干 / 超量，一律拒绝。"""
    bad_answer = _valid_payload()
    bad_answer["items"][0]["answer"] = "矩阵满秩"
    with pytest.raises(QuizSchemaError, match="答案不在选项中"):
        validate_quiz_payload(bad_answer, expected_count=5)

    few_options = _valid_payload()
    few_options["items"][0]["options"] = ["只有一个", "矩阵不可逆"]
    few_options["items"][0]["answer"] = "矩阵不可逆"
    validate_quiz_payload(few_options, expected_count=5)  # 2 个选项合法
    few_options["items"][0]["options"] = ["矩阵不可逆"]
    with pytest.raises(QuizSchemaError, match="至少 2 个选项"):
        validate_quiz_payload(few_options, expected_count=5)

    empty_stem = _valid_payload()
    empty_stem["items"][0]["stem"] = "  "
    with pytest.raises(QuizSchemaError, match="题干为空"):
        validate_quiz_payload(empty_stem, expected_count=5)

    duplicated = _valid_payload()
    duplicated["items"][1]["stem"] = duplicated["items"][0]["stem"]
    with pytest.raises(QuizSchemaError, match="重复"):
        validate_quiz_payload(duplicated, expected_count=5)

    with pytest.raises(QuizSchemaError, match="题目数量"):
        validate_quiz_payload(_valid_payload(), expected_count=1)


def test_create_and_grade_quiz_choice_and_short(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """choice 机器精确判分；short 走模型判分（monkeypatch DeepSeek 判分）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.database import Base
    from app.db.models import Course, Quiz, QuizAttempt

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="线性代数")
        db.add(course)
        db.flush()
        payload = _valid_payload()
        quiz = create_quiz(
            db, course_id=course.id, conversation_id=None, material_id=None,
            title=payload["title"], items=payload["items"],
        )
        items = {item.seq: item for item in quiz.items}

        class FakeJudge:
            def __init__(self) -> None:
                self.configured = True

            def complete_json(self, messages, *, max_tokens=0):
                return {"correct": True, "comment": "要点覆盖"}

        monkeypatch.setattr("app.services.quiz.DeepSeekClient", FakeJudge)
        results = grade_answers(db, quiz, [
            {"item_id": items[1].id, "answer": "矩阵不可逆"},      # choice 对
            {"item_id": items[2].id, "answer": "体积缩放因子，方向可能翻转"},  # short 模型判对
        ])
        assert [item["correct"] for item in results] == [True, True]
        attempts = db.query(QuizAttempt).all()
        assert len(attempts) == 2
        assert all(item.difficulty == "自适应" for item in quiz.items), "未指定难度时落默认标签"
        db.expire_all()
        refreshed = db.get(Quiz, quiz.id)
        assert refreshed.status == "completed", "全部题目都有作答 → 卷子完成"


def test_generate_quiz_tool_creates_quiz_and_suggestion(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """generate_quiz 工具端到端：落库 + suggestion 回前端；schema 失败降级为文本。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.ai.agent_tools import execute_tool
    from app.db.database import Base
    from app.db.models import Material, MaterialPage, Quiz, Course, KnowledgeNode, Note
    import app.services.quiz as quiz_service

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="线性代数")
        node = KnowledgeNode(course_id=None, name="行列式")
        db.add(course)
        db.flush()
        node.course_id = course.id  # knowledge_nodes.course_id 非空，先落课程再挂节点
        db.add(node)
        db.flush()
        material = Material(
            course_id=course.id, lecture_title="第1讲 行列式", original_filename="a.pptx",
            stored_filename="a.pptx", size_bytes=10, status="completed", page_count=1,
        )
        db.add(material)
        db.flush()
        db.add(MaterialPage(material_id=material.id, page_number=1, raw_text="行列式是线性代数的基本工具，行列式为零等价于矩阵不可逆。"))
        note = Note(course_id=course.id, knowledge_node_id=node.id, material_id=material.id, title="行列式", content_markdown="# 行列式")
        db.add(note)
        db.commit()

        def fake_generate(source, *, count, focus, course_name, difficulty=""):
            assert "行列式为零" in source, "素材应来自课件原文"
            return {
                "title": "行列式小测",
                "items": [{
                    "type": "choice", "stem": "行列式为零说明？",
                    "options": ["可逆", "不可逆"], "answer": "不可逆", "explanation": "材料原话",
                }],
            }

        monkeypatch.setattr(quiz_service, "generate_quiz_payload", fake_generate)
        outcome = execute_tool(
            db, course_id=course.id, name="generate_quiz",
            arguments={"material_id": material.id, "count": 1, "focus": "行列式"},
            scope="course", allow_quiz=True,
        )
        assert "1 道自测题" in outcome.summary
        assert outcome.suggestions and outcome.suggestions[0]["type"] == "quiz"
        db.expire_all()
        assert db.query(Quiz).count() == 1, "卷子应已落库（工具会话内显式提交）"

        # schema 失败：降级为文本回模型，不抛异常
        def bad_generate(source, *, count, focus, course_name, difficulty=""):
            raise quiz_service.QuizSchemaError("第 1 题答案不在选项中")

        monkeypatch.setattr(quiz_service, "generate_quiz_payload", bad_generate)
        failed = execute_tool(
            db, course_id=course.id, name="generate_quiz",
            arguments={"material_id": material.id}, scope="course", allow_quiz=True,
        )
        assert "未通过校验" in failed.summary


def _sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.database import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_list_course_mistakes_uses_latest_attempt() -> None:
    """错题本（§7 第一批）：以最近一次作答为准——后来答对即移出；错次按历史累计。"""
    from datetime import timedelta

    from app.db.models import Course, Material, QuizAttempt, utc_now
    from app.services.quiz import list_course_mistakes

    with _sqlite_session() as db:
        course = Course(name="线性代数")
        db.add(course)
        db.flush()
        material = Material(
            course_id=course.id, lecture_title="第1讲 行列式", original_filename="a.pptx",
            stored_filename="a.pptx", size_bytes=10, status="completed", page_count=1,
        )
        db.add(material)
        db.flush()
        quiz = create_quiz(
            db, course_id=course.id, conversation_id=None, material_id=material.id,
            title="行列式小测", items=_valid_payload()["items"],
        )
        items = {item.seq: item for item in quiz.items}
        now = utc_now()

        # 第 1 题：先错后对 → 应移出错题本
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=items[1].id, answer="矩阵可逆", correct=False, created_at=now))
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=items[1].id, answer="矩阵不可逆", correct=True, created_at=now + timedelta(seconds=1)))
        # 第 2 题：连续错两次 → 错题本保留，错次=2
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=items[2].id, answer="体积", correct=False, created_at=now))
        db.add(QuizAttempt(quiz_id=quiz.id, item_id=items[2].id, answer="面积", correct=False, created_at=now + timedelta(seconds=2)))
        db.commit()

        mistakes = list_course_mistakes(db, course.id)
        assert [entry["item_id"] for entry in mistakes] == [items[2].id]
        assert mistakes[0]["wrong_count"] == 2
        assert mistakes[0]["material_title"] == "第1讲 行列式"
        assert mistakes[0]["last_answer"] == "面积", "展示最近一次的错误答案"


def test_short_answer_returns_point_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """B1 结构化判分：简答题返回要点命中明细，而不只是一句点评。"""
    from app.db.models import Course
    from app.services.quiz import grade_answers

    with _sqlite_session() as db:
        course = Course(name="线性代数")
        db.add(course)
        db.flush()
        quiz = create_quiz(
            db, course_id=course.id, conversation_id=None, material_id=None,
            title="行列式小测", items=_valid_payload()["items"],
        )
        items = {item.seq: item for item in quiz.items}

        class FakeJudge:
            configured = True

            def complete_json(self, messages, *, max_tokens=0):
                return {
                    "correct": False,
                    "comment": "缺少方向可能翻转这一点",
                    "points": [
                        {"point": "行向量张成的体积/缩放因子", "hit": True},
                        {"point": "方向可能翻转", "hit": False},
                    ],
                }

        monkeypatch.setattr("app.services.quiz.DeepSeekClient", FakeJudge)
        results = grade_answers(db, quiz, [{"item_id": items[2].id, "answer": "体积缩放因子"}])
        assert results[0]["points"] == [
            {"point": "行向量张成的体积/缩放因子", "hit": True},
            {"point": "方向可能翻转", "hit": False},
        ]
        assert results[0]["correct"] is False


def test_validate_quiz_points_drops_unverifiable_evidence() -> None:
    """考点规划的硬门槛：evidence 回查不到材料 → 该考点直接丢弃，不进入出题。"""
    from app.services.quiz import validate_quiz_points

    source = "系统需求包括功能需求与非功能需求。性能属于非功能需求。"
    points = validate_quiz_points({
        "points": [
            {"point": "系统需求构成", "evidence": "系统需求包括功能需求与非功能需求", "level": "basic"},
            {"point": "凭空捏造", "evidence": "材料里没有这句话", "level": "advanced"},
        ],
    }, source, expected=3)
    assert [point["point"] for point in points] == ["系统需求构成"]


def test_review_quiz_item_machine_gates() -> None:
    """质量审查三条机器规则：逃逸项 / 题干泄答案 / 解析无依据。"""
    from app.services.quiz import review_quiz_item

    point = {"point": "系统需求", "evidence": "系统需求包括功能需求与非功能需求"}
    base = {
        "type": "choice", "stem": "系统需求包括什么？",
        "options": ["功能与非功能需求", "只有功能需求"],
        "answer": "功能与非功能需求",
        "explanation": "材料指出：系统需求包括功能需求与非功能需求。",
    }
    assert review_quiz_item(base, point) is None

    escape = {**base, "options": ["功能与非功能需求", "以上都不对"]}
    assert "逃逸项" in (review_quiz_item(escape, point) or "")

    leak = {**base, "stem": "系统需求包括功能与非功能需求，对吗？"}
    assert "包含了答案" in (review_quiz_item(leak, point) or "")

    no_evidence = {**base, "explanation": "这是常识。"}
    assert "没有引用材料原句" in (review_quiz_item(no_evidence, point) or "")


def _fake_two_stage(responses: list[dict]):
    calls: list[int] = []

    class FakeClient:
        configured = True

        def complete_json(self, messages, *, max_tokens=0):
            index = min(len(calls), len(responses) - 1)
            calls.append(index)
            return responses[index]

    return FakeClient, calls


def test_generate_quiz_two_stage_repairs_bad_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """坏题（解析无依据）被审查挑出 → 单题返修 → 合格的题带用户难度落库。"""
    import app.services.quiz as quiz_service

    source = "系统需求包括功能需求与非功能需求。性能属于非功能需求。"
    plan = {"points": [{"point": "系统需求构成", "evidence": "系统需求包括功能需求与非功能需求", "level": "basic"}]}
    bad = {
        "point_index": 1, "type": "choice", "stem": "系统需求包括哪些？",
        "options": ["功能与非功能需求", "只有功能需求"],
        "answer": "功能与非功能需求", "explanation": "这是常识。",
    }
    good = {
        "point_index": 1, "type": "choice", "stem": "系统需求包括哪些内容？",
        "options": ["功能与非功能需求", "只有功能需求"],
        "answer": "功能与非功能需求", "explanation": "材料指出：系统需求包括功能需求与非功能需求。",
    }
    FakeClient, calls = _fake_two_stage([plan, {"title": "系统需求小测", "items": [bad]}, {"items": [good]}])
    monkeypatch.setattr(quiz_service, "DeepSeekClient", FakeClient)

    payload = quiz_service.generate_quiz_payload(
        source, count=1, focus="", course_name="软件", difficulty="期末",
    )
    assert payload["title"] == "系统需求小测"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["difficulty"] == "期末"
    assert "系统需求包括功能需求与非功能需求" in payload["items"][0]["explanation"]
    assert len(calls) == 3, "规划 + 生成 + 返修各一次"


def test_generate_quiz_raises_when_all_items_fail_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """返修后仍不合格 → 宁可报错，也不把废题塞给学生。"""
    import app.services.quiz as quiz_service

    source = "系统需求包括功能需求与非功能需求。"
    plan = {"points": [{"point": "系统需求构成", "evidence": "系统需求包括功能需求与非功能需求", "level": "basic"}]}
    bad = {
        "point_index": 1, "type": "choice", "stem": "系统需求包括哪些？",
        "options": ["功能与非功能需求", "只有功能需求"],
        "answer": "功能与非功能需求", "explanation": "这是常识。",
    }
    FakeClient, _calls = _fake_two_stage([plan, {"items": [bad]}, {"items": [bad]}])
    monkeypatch.setattr(quiz_service, "DeepSeekClient", FakeClient)

    with pytest.raises(quiz_service.QuizSchemaError, match="质量审查"):
        quiz_service.generate_quiz_payload(source, count=1, focus="", course_name="软件")
