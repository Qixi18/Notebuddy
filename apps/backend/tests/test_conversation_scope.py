"""Conversation ownership: scope is unified to course / global / note."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Course
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
    return TestClient(app), course_id


def test_note_scope_persists_snapshot(tmp_path) -> None:
    client, course_id = _client(tmp_path)
    try:
        created = client.post(
            f"/api/v1/courses/{course_id}/conversations",
            json={"title": "锁定笔记", "scope": "note", "note_id": "n-1", "note_title": "红黑树的五个不变量"},
        ).json()
        assert created["scope"] == "note"
        assert created["note_id"] == "n-1"
        assert created["note_title"] == "红黑树的五个不变量"
        assert created["default_scope"] == "note"
    finally:
        app.dependency_overrides.clear()


def test_legacy_material_folds_into_course_and_drops_note(tmp_path) -> None:
    client, course_id = _client(tmp_path)
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
    client, course_id = _client(tmp_path)
    try:
        client.post(
            f"/api/v1/courses/{course_id}/conversations",
            json={"title": "跨课程", "scope": "global"},
        )
        listed = client.get(f"/api/v1/courses/{course_id}/conversations").json()
        assert [item["scope"] for item in listed] == ["global"]
    finally:
        app.dependency_overrides.clear()
