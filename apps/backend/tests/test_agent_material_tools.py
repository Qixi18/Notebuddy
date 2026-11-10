"""课件阅读工具（read_material_page / list_course_materials）的注册与归属测试。

来源：`fix/assistant-agent-scope` 的 P4 批次。按 feat/overall-inspection 的当前契约
**只搬运只读工具**：
- 发现模式的 `propose_notebook_edits` 仍按 P0-QA-06 保持停用（见下 test 与
  test_agent_notebook.py 的既有断言），本文件固定这一边界，避免后续误开放。
"""

from __future__ import annotations

from app.ai.agent_tools import build_tool_specs, execute_tool
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_material,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


def _spec_names(**kwargs) -> set[str]:
    return {spec["function"]["name"] for spec in build_tool_specs(**kwargs)}


def test_material_tools_registered_for_course_and_global(session):
    for scope in ("course", "global"):
        names = _spec_names(scope=scope, editable_notebook=False)
        assert "read_material_page" in names
        assert "list_course_materials" in names


def test_material_tools_not_registered_in_note_scope(session):
    names = _spec_names(scope="note", editable_notebook=True)
    assert "read_material_page" not in names
    assert "list_course_materials" not in names


def test_propose_notebook_edits_only_with_editable_notebook():
    """ADR-0005 修订 P0-QA-06：编辑建议工具仅在有可编辑 Notebook 时暴露，
    且只创建待审建议——Agent 写正文的唯一路径仍是待审审核 + 受控 CAS 应用。"""

    for scope in ("course", "global", "note"):
        names = _spec_names(scope=scope, editable_notebook=True)
        assert "propose_notebook_edits" in names
    for scope in ("course", "global", "note"):
        names = _spec_names(scope=scope, editable_notebook=False)
        assert "propose_notebook_edits" not in names
    assert "propose_knowledge_node" in _spec_names(scope="course", editable_notebook=True)


def test_list_course_materials_and_page_reading(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    material = make_material(session, book, asset, title="第 1 讲")
    persist_ir(session, book, asset)
    session.commit()

    listed = execute_tool(
        session, course_id=course.id, name="list_course_materials",
        arguments={}, scope="course",
    )
    assert "第 1 讲" in listed.payload_text and material.id in listed.payload_text

    page = execute_tool(
        session, course_id=course.id, name="read_material_page",
        arguments={"material_id": material.id, "page_number": 1}, scope="course",
    )
    assert "第 1 页" in page.summary
    assert "极限" in page.payload_text

    beyond = execute_tool(
        session, course_id=course.id, name="read_material_page",
        arguments={"material_id": material.id, "page_number": 9}, scope="course",
    )
    assert "页码越界" in beyond.summary


def test_read_material_page_requires_existing_material(session):
    course = make_course(session)
    session.commit()
    missing = execute_tool(
        session, course_id=course.id, name="read_material_page",
        arguments={"material_id": "not-a-material", "page_number": 1}, scope="course",
    )
    assert missing.summary == "资料不可用"


def test_read_material_page_enforces_course_scope(session):
    course = make_course(session)
    foreign_course = make_course(session, name="别的课")
    foreign_book = make_notebook(session, foreign_course)
    foreign_asset = make_asset(session, foreign_book)
    foreign_material = make_material(session, foreign_book, foreign_asset, title="外课资料")
    persist_ir(session, foreign_book, foreign_asset)
    session.commit()

    outcome = execute_tool(
        session, course_id=course.id, name="read_material_page",
        arguments={"material_id": foreign_material.id, "page_number": 1}, scope="course",
    )
    assert "不属于当前课程" in outcome.payload_text


def test_read_material_page_rejects_invalid_page_number(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    material = make_material(session, book, asset, title="第 2 讲")
    persist_ir(session, book, asset)
    session.commit()

    outcome = execute_tool(
        session, course_id=course.id, name="read_material_page",
        arguments={"material_id": material.id, "page_number": "abc"}, scope="course",
    )
    assert outcome.summary == "页码无效"
