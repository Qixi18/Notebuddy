"""Agent 工具的权限闸门与跨课程隔离。

这三条是数据边界的关键点，此前没有测试覆盖：
1. 学习技能（出题/提纲/对比）即使模型硬调，只要 ``allow_quiz=False`` 也必须被拒，
   且不能留下任何 Quiz / ReviewArtifact 行；
2. 没有模型时必须降级为工具失败，不能静默写入半成品；
3. 会话消息搜索必须按课程隔离，且 LIKE 通配符不能扩大命中范围。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.ai.agent_read_tools import load_notebook
from app.ai.agent_tools import execute_tool
from app.db.models import Conversation, ConversationMessage, Quiz, ReviewArtifact
from app.services.conversations import search_course_messages
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]

LEARNING_TOOLS = ("generate_quiz", "generate_review_outline", "generate_concept_contrast")


def _course_with_body(session):
    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    persist_ir(session, book, asset)
    session.commit()
    return course, book


def _learning_row_counts(session) -> tuple[int, int]:
    session.expire_all()
    return (
        session.scalar(select(func.count()).select_from(Quiz)) or 0,
        session.scalar(select(func.count()).select_from(ReviewArtifact)) or 0,
    )


def test_learning_tools_are_refused_when_not_enabled(session):
    """模型不听话硬调工具也不行：开关关掉就必须拒绝，且零副作用。"""
    course, book = _course_with_body(session)
    before = _learning_row_counts(session)

    for name in LEARNING_TOOLS:
        outcome = execute_tool(
            session, course_id=course.id, name=name,
            arguments={"count": 3, "focus": "复杂度"},
            scope="course", editable_notebook_id=book.id,
            allow_quiz=False,
        )
        assert "未启用" in outcome.summary, (name, outcome.summary)
        assert "未启用" in outcome.payload_text, (name, outcome.payload_text)

    assert _learning_row_counts(session) == before == (0, 0)


def test_quiz_tool_without_model_degrades_and_writes_nothing(session):
    """开关打开但没配模型：必须报失败，不能留下空卷或半成品。"""
    course, book = _course_with_body(session)

    outcome = execute_tool(
        session, course_id=course.id, name="generate_quiz",
        arguments={"count": 3}, scope="course",
        editable_notebook_id=book.id, allow_quiz=True,
    )

    assert "失败" in outcome.summary, outcome.summary
    assert _learning_row_counts(session) == (0, 0)


def test_learning_tool_without_any_source_is_refused_before_model(session):
    """课程没有任何正文/资料时，应直接说没材料，而不是先去调模型。"""
    course = make_course(session, "空课程")
    session.commit()

    outcome = execute_tool(
        session, course_id=course.id, name="generate_review_outline",
        arguments={}, scope="course", allow_quiz=True,
    )

    assert "材料" in outcome.summary, outcome.summary
    assert _learning_row_counts(session) == (0, 0)


def test_load_notebook_rejects_foreign_and_deleted_notes(session):
    course, book = _course_with_body(session)
    other_course = make_course(session, "别的课")
    foreign = make_notebook(session, other_course)
    session.commit()

    loaded, error = load_notebook(session, course.id, foreign.id)
    assert loaded is None
    assert "不属于当前课程" in error

    book.deleted_at = datetime(2026, 10, 29, tzinfo=UTC)
    session.commit()
    loaded, error = load_notebook(session, course.id, book.id)
    assert loaded is None
    assert "不存在" in error


def _conversation_with_message(session, course, content: str) -> Conversation:
    conversation = Conversation(
        course_id=course.id, title=f"{course.name} 对话", default_scope="course",
    )
    session.add(conversation)
    session.flush()
    session.add(ConversationMessage(
        conversation_id=conversation.id, role="user", content=content, status="completed",
    ))
    session.commit()
    return conversation


def test_conversation_search_is_scoped_to_course(session):
    mine = make_course(session, "第一门课")
    other = make_course(session, "第二门课")
    session.commit()
    my_conversation = _conversation_with_message(session, mine, "这道题涉及平衡二叉树吗？")
    other_conversation = _conversation_with_message(session, other, "平衡二叉树的旋转怎么写？")

    hits = search_course_messages(session, mine.id, "平衡二叉树")
    assert [hit["conversation_id"] for hit in hits] == [my_conversation.id]
    assert [hit["conversation_id"] for hit in search_course_messages(session, other.id, "平衡二叉树")] == [
        other_conversation.id
    ]
    # 没命中的课程不能返回别人的消息
    third = make_course(session, "第三门课")
    session.commit()
    assert search_course_messages(session, third.id, "平衡二叉树") == []


def test_conversation_search_escapes_like_wildcards(session):
    course = make_course(session)
    session.commit()
    _conversation_with_message(session, course, "普通内容，没有百分号")

    # 通配符必须被转义：否则 % 会命中所有消息
    assert search_course_messages(session, course.id, "%") == []
    assert search_course_messages(session, course.id, "_") == []
    assert search_course_messages(session, course.id, "") == []
    assert len(search_course_messages(session, course.id, "普通内容")) == 1
