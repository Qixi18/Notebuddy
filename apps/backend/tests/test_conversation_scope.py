"""Conversation ownership: scope is unified to course / global / note."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Course, Notebook
from app.main import app


def _client(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'scope.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with factory() as db:
        course = Course(name="软件")
        db.add(course)
        db.commit()
        course_id = course.id
        notebook = Notebook(course_id=course_id, title="红黑树", tree_slot=0)
        db.add(notebook)
        db.commit()
        notebook_id = notebook.id
    return TestClient(app), course_id, notebook_id


def test_note_scope_persists_snapshot(tmp_path) -> None:
    client, course_id, notebook_id = _client(tmp_path)
    try:
        created = client.post(
            f"/api/v1/courses/{course_id}/conversations",
            json={"title": "锁定笔记", "scope": "note", "note_id": notebook_id, "note_title": "红黑树的五个不变量"},
        ).json()
        assert created["scope"] == "note"
        assert created["note_id"] == notebook_id
        assert created["note_title"] == "红黑树的五个不变量"
        assert created["default_scope"] == "note"
    finally:
        app.dependency_overrides.clear()


def test_legacy_material_folds_into_course_and_drops_note(tmp_path) -> None:
    client, course_id, _notebook_id = _client(tmp_path)
    try:
        created = client.post(
            f"/api/v1/courses/{course_id}/conversations",
            json={"title": "旧词", "default_scope": "material", "note_id": "should-drop", "note_title": "x"},
        ).json()
        assert created["scope"] == "course"
        assert created["default_scope"] == "course"
        # 非 note 范围不保留笔记快照，避免脏字段混进历史分组
        assert created["note_id"] is None
        assert created["note_title"] is None
    finally:
        app.dependency_overrides.clear()


def test_global_scope_and_list_returns_it(tmp_path) -> None:
    client, course_id, _notebook_id = _client(tmp_path)
    try:
        client.post(
            f"/api/v1/courses/{course_id}/conversations",
            json={"title": "跨课程", "scope": "global"},
        )
        listed = client.get(f"/api/v1/courses/{course_id}/conversations").json()
        assert [item["scope"] for item in listed] == ["global"]
    finally:
        app.dependency_overrides.clear()


def test_notebook_conversation_has_no_course_and_is_listed_by_notebook(tmp_path) -> None:
    client, course_id, notebook_id = _client(tmp_path)
    try:
        created = client.post(
            f"/api/v1/notebooks/{notebook_id}/conversations", json={"title": "Notebook 问答"},
        )
        assert created.status_code == 201
        row = created.json()
        assert row["scope"] == "notebook"
        assert row["default_scope"] == "notebook"
        assert row["notebook_id"] == notebook_id
        assert row["course_id"] is None
        assert client.get(f"/api/v1/notebooks/{notebook_id}/conversations").json() == [row]
        assert client.get(f"/api/v1/courses/{course_id}/conversations").json() == []
        assert client.get(f"/api/v1/conversations/{row['id']}/messages").json() == []
        rejected = client.post(
            f"/api/v1/conversations/{row['id']}/messages", json={"question": "test"},
        )
        assert rejected.status_code == 409
        assert "Notebook 专属问答服务" in rejected.json()["detail"]
        agent_rejected = client.post(
            f"/api/v1/conversations/{row['id']}/agent-messages",
            json={"question": "test", "scope": "notebook", "notebook_context": {
                "course_id": None, "notebook_id": notebook_id, "revision": 0,
            }},
        )
        assert agent_rejected.status_code == 409

        unbound = client.post("/api/v1/notebooks/unbound", json={"title": "未分类 Notebook"})
        assert unbound.status_code == 201
        unbound_id = unbound.json()["id"]
        unbound_conversation = client.post(
            f"/api/v1/notebooks/{unbound_id}/conversations", json={"title": "未分类会话"},
        )
        assert unbound_conversation.status_code == 201
        assert unbound_conversation.json()["course_id"] is None
        assert unbound_conversation.json()["notebook_id"] == unbound_id
    finally:
        app.dependency_overrides.clear()
