"""课程生命周期接口测试：重命名与级联删除。

用例锁定两条约束：
- 重命名只接受合法名称，空名/越界字段必须被拒；
- 删除必须彻底清理课程下所有关联数据，且不留孤儿记录。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    Course,
    KnowledgeNode,
    Material,
    MaterialPage,
    Note,
    NoteRevision,
    PageBlock,
    RetrievalChunk,
    SourceRef,
    knowledge_node_source_refs,
    note_source_refs,
)
from app.main import app


@pytest.fixture()
def db_session() -> Session:
    """每个用例一套独立的内存库。"""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    """复用同一个 Session，便于用例直接断言库内状态。"""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_course(db: Session) -> str:
    """构造一份最小但带完整关联链的课程数据。"""
    course = Course(name="线性代数")
    db.add(course)
    db.flush()

    material = Material(
        course_id=course.id,
        lecture_title="第一讲",
        original_filename="lecture1.pptx",
        stored_filename="stored-1.pptx",
        size_bytes=1024,
    )
    db.add(material)
    db.flush()

    page = MaterialPage(material_id=material.id, page_number=1, raw_text="矩阵的定义")
    db.add(page)
    db.flush()

    block = PageBlock(page_id=page.id, block_type="text", content="矩阵的定义", position=0)
    db.add(block)
    db.flush()

    ref = SourceRef(page_block_id=block.id, quote="矩阵的定义")
    db.add(ref)

    db.add(RetrievalChunk(course_id=course.id, page_block_id=block.id, text="矩阵的定义"))

    node = KnowledgeNode(course_id=course.id, name="矩阵")
    db.add(node)
    db.flush()

    note = Note(
        course_id=course.id,
        knowledge_node_id=node.id,
        title="矩阵",
        content_markdown="# 矩阵",
    )
    db.add(note)
    db.flush()

    db.add(
        NoteRevision(
            note_id=note.id, revision_number=1, content_markdown="# 矩阵", content_origin="ai"
        )
    )
    note.source_refs.append(ref)
    node.source_refs.append(ref)

    db.commit()
    return course.id


def test_rename_course_trims_whitespace(client: TestClient, db_session: Session) -> None:
    course_id = _seed_course(db_session)

    response = client.patch(f"/api/v1/courses/{course_id}", json={"name": "  高等代数  "})
    assert response.status_code == 200
    assert response.json()["name"] == "高等代数"


def test_rename_course_rejects_blank_name(client: TestClient, db_session: Session) -> None:
    course_id = _seed_course(db_session)

    response = client.patch(f"/api/v1/courses/{course_id}", json={"name": "   "})
    assert response.status_code == 400


def test_rename_course_rejects_unknown_field(client: TestClient, db_session: Session) -> None:
    course_id = _seed_course(db_session)

    response = client.patch(
        f"/api/v1/courses/{course_id}", json={"name": "合法名", "course_id": "hack"}
    )
    assert response.status_code == 422


def test_rename_missing_course_returns_404(client: TestClient) -> None:
    response = client.patch("/api/v1/courses/not-a-real-id", json={"name": "x"})
    assert response.status_code == 404


def test_delete_course_preserves_rows_for_restore(client: TestClient, db_session: Session, monkeypatch) -> None:
    # File checkpoint itself has dedicated integration tests; this fixture is in-memory.
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    course_id = _seed_course(db_session)

    response = client.delete(f"/api/v1/courses/{course_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["course_id"] == course_id
    assert body["materials"] == 1
    assert body["pages"] == 1
    assert body["knowledge_nodes_touched"] == 1
    assert body["action"] == "soft_delete_with_checkpoint"
    assert db_session.get(Course, course_id).deleted_at is not None
    assert client.get("/api/v1/courses").json() == []

    db_session.expire_all()
    for model in (
        Course,
        Material,
        MaterialPage,
        PageBlock,
        SourceRef,
        RetrievalChunk,
        KnowledgeNode,
        Note,
        NoteRevision,
    ):
        count = int(db_session.scalar(select(func.count()).select_from(model)) or 0)
        assert count == 1, f"{model.__tablename__} 应保留以便恢复"

    for table in (note_source_refs, knowledge_node_source_refs):
        count = int(db_session.scalar(select(func.count()).select_from(table)) or 0)
        assert count == 1, f"{table.name} 应保留以便恢复"
    assert client.post(f"/api/v1/courses/{course_id}/restore").status_code == 200
    assert client.get("/api/v1/courses").json()[0]["id"] == course_id


def test_delete_missing_course_returns_404(client: TestClient) -> None:
    response = client.delete("/api/v1/courses/not-a-real-id")
    assert response.status_code == 404
