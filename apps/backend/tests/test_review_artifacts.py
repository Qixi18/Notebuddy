"""复习产物（复习提纲 / 易混概念）的课程隔离与软移除语义。

这些产物是技能卡跨会话的数据真源，必须满足：
- 按课程列出时只返回本课程的产物，不能串课；
- 「移出复习」是软移除：行保留、可恢复，默认列表不含它；
- kind 过滤只返回对应类型。
"""

from __future__ import annotations

from app.services.quiz import (
    create_review_artifact,
    list_review_artifacts,
    update_review_artifact,
)
from tests.notebook_fixtures import make_course

pytest_plugins = ["tests.notebook_fixtures"]


def _outline(title: str) -> dict:
    return {"title": title, "modules": [{"title": "模块", "priority": "high", "items": []}]}


def test_review_artifacts_are_scoped_to_their_course(session):
    first = make_course(session, "第一门课")
    second = make_course(session, "第二门课")
    mine = create_review_artifact(
        session, course_id=first.id, conversation_id=None,
        kind="review_outline", title="本课提纲", payload=_outline("本课提纲"),
    )
    create_review_artifact(
        session, course_id=second.id, conversation_id=None,
        kind="review_outline", title="别课提纲", payload=_outline("别课提纲"),
    )
    session.commit()

    listed = list_review_artifacts(session, course_id=first.id)
    assert [row["id"] for row in listed] == [mine.id]
    assert listed[0]["payload"]["title"] == "本课提纲"

    # 未指定课程时才可能看到全部；面板永远带课程，所以这条只是确认实现语义
    assert len(list_review_artifacts(session)) == 2


def test_dismissing_artifact_is_soft_and_reversible(session):
    course = make_course(session)
    artifact = create_review_artifact(
        session, course_id=course.id, conversation_id=None,
        kind="concept_contrast", title="对比", payload={"pairs": []},
    )
    session.commit()

    updated = update_review_artifact(session, artifact.id, dismissed=True)
    assert updated == {"id": artifact.id, "favorite": False, "dismissed": True}

    # 默认列表（面板主动区）不再返回，但行仍在，可以恢复
    assert [row["id"] for row in list_review_artifacts(session, course_id=course.id)] == []
    dismissed = list_review_artifacts(session, course_id=course.id, include_dismissed=True)
    assert [row["id"] for row in dismissed] == [artifact.id]
    assert dismissed[0]["dismissed"] is True

    update_review_artifact(session, artifact.id, dismissed=False)
    assert [row["id"] for row in list_review_artifacts(session, course_id=course.id)] == [
        artifact.id
    ]


def test_favorite_and_kind_filter(session):
    course = make_course(session)
    outline = create_review_artifact(
        session, course_id=course.id, conversation_id=None,
        kind="review_outline", title="提纲", payload=_outline("提纲"),
    )
    create_review_artifact(
        session, course_id=course.id, conversation_id=None,
        kind="concept_contrast", title="对比", payload={"pairs": []},
    )
    session.commit()

    update_review_artifact(session, outline.id, favorite=True)
    favorites = [row for row in list_review_artifacts(session, course_id=course.id) if row["favorite"]]
    assert [row["id"] for row in favorites] == [outline.id]

    only_outline = list_review_artifacts(session, course_id=course.id, kind="review_outline")
    assert [row["kind"] for row in only_outline] == ["review_outline"]


def test_missing_artifact_updates_report_none(session):
    assert update_review_artifact(session, "does-not-exist", favorite=True) is None
