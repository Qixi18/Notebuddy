"""答疑技能（复习提纲 / 易混概念）测试：schema 硬门 + 工具端到端 + 开关注册。"""

from __future__ import annotations

import pytest

from app.services.skills import (
    SkillSchemaError,
    validate_contrast_payload,
    validate_outline_payload,
)


def test_validate_outline_accepts_wellformed() -> None:
    payload = validate_outline_payload({
        "title": "行列式复习",
        "modules": [
            {"title": "定义", "priority": "high", "items": [{"point": "行列式的代数定义", "ref": "第 1 页"}]},
            {"title": "性质", "items": [{"point": "为零等价于不可逆"}]},
        ],
    })
    assert payload["modules"][0]["priority"] == "high"
    assert payload["modules"][1]["priority"] == "medium", "缺省优先级应为 medium"
    assert payload["modules"][1]["items"][0]["ref"] == ""


def test_validate_outline_hard_gates() -> None:
    with pytest.raises(SkillSchemaError):
        validate_outline_payload({"modules": [{"title": "只有一个模块", "items": [{"point": "x"}]}]})
    with pytest.raises(SkillSchemaError):
        validate_outline_payload({"modules": [
            {"title": "A", "items": [{"point": ""}]},
            {"title": "B", "items": [{"point": "x"}]},
        ]})
    with pytest.raises(SkillSchemaError):
        validate_outline_payload({"modules": [
            {"title": "A", "items": [{"point": "x"}]},
            {"title": "A", "items": [{"point": "x"}]},
        ]})


def test_validate_contrast_accepts_wellformed() -> None:
    payload = validate_contrast_payload({"pairs": [{
        "a": "内聚", "b": "耦合", "core": "内聚看模块内部，耦合看模块之间",
        "dimensions": [{"name": "定义", "a": "内部", "b": "之间"}, {"name": "目标", "a": "高", "b": "低"}],
        "anchor": "高内聚低耦合",
    }]})
    assert payload["pairs"][0]["anchor"] == "高内聚低耦合"


def test_validate_contrast_hard_gates() -> None:
    with pytest.raises(SkillSchemaError, match="相同"):
        validate_contrast_payload({"pairs": [{"a": "X", "b": "X", "core": "c", "dimensions": [
            {"name": "d", "a": "1", "b": "2"}, {"name": "e", "a": "1", "b": "2"}]}]})
    with pytest.raises(SkillSchemaError, match="维度"):
        validate_contrast_payload({"pairs": [{"a": "A", "b": "B", "core": "c", "dimensions": [
            {"name": "d", "a": "1", "b": "2"}]}]})
    with pytest.raises(SkillSchemaError, match="核心区别"):
        validate_contrast_payload({"pairs": [{"a": "A", "b": "B", "core": "", "dimensions": [
            {"name": "d", "a": "1", "b": "2"}, {"name": "e", "a": "1", "b": "2"}]}]})


@pytest.fixture()
def skill_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.database import Base
    from app.db.models import Course, KnowledgeNode, Material, MaterialPage, Note

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="软件工程")
        node = KnowledgeNode(course_id=None, name="内聚")
        db.add(course)
        db.flush()
        node.course_id = course.id
        db.add(node)
        db.flush()
        material = Material(
            course_id=course.id, lecture_title="第1讲 需求", original_filename="a.pptx",
            stored_filename="a.pptx", size_bytes=10, status="completed", page_count=1,
        )
        db.add(material)
        db.flush()
        db.add(MaterialPage(material_id=material.id, page_number=1, raw_text="内聚是模块内部的紧密程度，耦合是模块之间的依赖程度。高内聚低耦合。"))
        db.add(Note(
            course_id=course.id, knowledge_node_id=node.id, material_id=material.id,
            title="内聚与耦合", content_markdown="内聚与耦合是模块设计的两个维度。",
        ))
        db.commit()
        yield db, course, material


def test_generate_outline_tool_returns_suggestion(skill_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.agent_tools import execute_tool
    import app.services.skills as skills_service

    db, course, material = skill_db

    def fake_generate(source, *, course_name, focus):
        assert "内聚是模块内部" in source, "素材应来自课件原文"
        return {
            "title": "需求复习提纲",
            "modules": [
                {"title": "模块设计", "priority": "high", "items": [{"point": "高内聚低耦合", "ref": "第 1 页"}]},
                {"title": "检验", "items": [{"point": "能否正确划分模块"}]},
            ],
        }

    monkeypatch.setattr(skills_service, "generate_review_outline_payload", fake_generate)
    outcome = execute_tool(
        db, course_id=course.id, name="generate_review_outline",
        arguments={"material_id": material.id, "focus": "模块设计"},
        scope="course", allow_quiz=True,
    )
    assert "复习提纲" in outcome.summary
    suggestion = outcome.suggestions[0]
    assert suggestion["type"] == "review_outline"
    assert suggestion["module_count"] == 2 and suggestion["item_count"] == 2
    assert suggestion["modules"][0]["items"][0]["ref"] == "第 1 页"


def test_generate_contrast_tool_returns_suggestion(skill_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.agent_tools import execute_tool
    import app.services.skills as skills_service

    db, course, _material = skill_db

    def fake_generate(source, *, course_name, focus):
        # 未指定课件 → 素材回退到课程笔记
        assert "内聚与耦合" in source
        return {"pairs": [{
            "a": "内聚", "b": "耦合", "core": "内部紧密 vs 之间依赖",
            "dimensions": [{"name": "对象", "a": "模块内部", "b": "模块之间"}, {"name": "目标", "a": "高", "b": "低"}],
            "anchor": "高内聚低耦合",
        }]}

    monkeypatch.setattr(skills_service, "generate_concept_contrast_payload", fake_generate)
    outcome = execute_tool(
        db, course_id=course.id, name="generate_concept_contrast",
        arguments={}, scope="course", allow_quiz=True,
    )
    assert "1 组" in outcome.summary
    suggestion = outcome.suggestions[0]
    assert suggestion["type"] == "concept_contrast"
    assert suggestion["pairs"][0]["a"] == "内聚"
    assert len(suggestion["pairs"][0]["dimensions"]) == 2


def test_skill_tool_degrades_schema_failure_to_text(skill_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.agent_tools import execute_tool
    import app.services.skills as skills_service

    db, course, material = skill_db

    def bad_generate(source, *, course_name, focus):
        raise SkillSchemaError("modules 应为 2-8 个")

    monkeypatch.setattr(skills_service, "generate_review_outline_payload", bad_generate)
    outcome = execute_tool(
        db, course_id=course.id, name="generate_review_outline",
        arguments={"material_id": material.id}, scope="course", allow_quiz=True,
    )
    assert "未通过校验" in outcome.summary
    assert outcome.suggestions == []


def test_skill_specs_registered_with_switch_in_all_scopes() -> None:
    from app.ai.agent_tools import build_tool_specs

    course_specs = [spec["function"]["name"] for spec in build_tool_specs(scope="course", editable_note=False, allow_quiz=True)]
    assert "generate_review_outline" in course_specs
    assert "generate_concept_contrast" in course_specs
    # note 档也注册：锁笔记会话里「考考我/复习提纲」不该哑火，素材自动落到锁定的笔记
    note_specs = [spec["function"]["name"] for spec in build_tool_specs(scope="note", editable_note=True, allow_quiz=True)]
    assert "generate_review_outline" in note_specs
    assert "generate_concept_contrast" in note_specs
    no_switch = [spec["function"]["name"] for spec in build_tool_specs(scope="course", editable_note=False, allow_quiz=False)]
    assert "generate_review_outline" not in no_switch, "技能族与 quiz 共用 allow 开关"


def test_quiz_tool_falls_back_to_course_notes_without_material(skill_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """没选课件也能出题：素材回退到课程小节笔记（修复「有时候不出卡」的空素材分支）。"""
    from app.ai.agent_tools import execute_tool
    import app.services.quiz as quiz_service

    db, course, _material = skill_db

    def fake_generate(source, *, count, focus, course_name, difficulty=""):
        assert "内聚与耦合是模块设计" in source, "素材应来自课程小节笔记"
        return {
            "title": "小测",
            "items": [{"type": "short", "stem": "高内聚低耦合是什么意思？", "answer": "模块内部紧密、模块之间少依赖", "explanation": ""}],
        }

    monkeypatch.setattr(quiz_service, "generate_quiz_payload", fake_generate)
    outcome = execute_tool(
        db, course_id=course.id, name="generate_quiz",
        arguments={},  # 不传 material_id / note_id
        scope="course", allow_quiz=True,
    )
    assert "自测题" in outcome.summary
    assert outcome.suggestions and outcome.suggestions[0]["type"] == "quiz"


def test_quiz_tool_defaults_to_locked_note_in_note_scope(skill_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.ai.agent_tools import execute_tool
    from app.db.database import Base
    from app.db.models import KnowledgeNode, Note
    import app.services.quiz as quiz_service

    db, course, _material = skill_db

    def fake_generate(source, *, count, focus, course_name, difficulty=""):
        assert "内聚与耦合" in source
        return {
            "title": "锁笔记小测",
            "items": [{"type": "short", "stem": "Q", "answer": "A", "explanation": ""}],
        }

    monkeypatch.setattr(quiz_service, "generate_quiz_payload", fake_generate)
    outcome = execute_tool(
        db, course_id=course.id, name="generate_quiz",
        arguments={},  # note 档不传 note_id → 自动落到锁定的笔记
        scope="note", locked_note_id=_locked_note_id(db, course.id), allow_quiz=True,
    )
    assert "自测题" in outcome.summary
    assert outcome.suggestions


def _locked_note_id(db, course_id: str) -> str:
    from sqlalchemy import select

    from app.db.models import Note

    return db.scalars(select(Note).where(Note.course_id == course_id)).first().id
