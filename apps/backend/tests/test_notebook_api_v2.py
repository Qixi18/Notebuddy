"""Notebook body outline, reading position, course tree and forest relations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.db.models import NotebookSection
from app.main import app
from app.notes.document import normalize_document
from app.notes.store import write_document
from tests.notebook_fixtures import (
    make_asset,
    make_course,
    make_material,
    make_notebook,
    persist_ir,
)

pytest_plugins = ["tests.notebook_fixtures"]


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _document(*headings: str) -> dict:
    content = []
    for index, heading in enumerate(headings, start=1):
        content.append({
            "type": "heading", "attrs": {"level": 1, "blockId": f"h-{index}"},
            "content": [{"type": "text", "text": heading}],
        })
        content.append({
            "type": "paragraph", "attrs": {"blockId": f"p-{index}"},
            "content": [{"type": "text", "text": f"{heading} 的正文内容，用于检索与目录。"}],
        })
    return normalize_document({"type": "doc", "content": content})


def _ready_book(session, *, title="笔记", course_name="数学"):
    course = make_course(session, course_name)
    book = make_notebook(session, course, title)
    asset = make_asset(session, book)
    make_material(session, book, asset)
    persist_ir(session, book, asset)
    write_document(session, book, _document("第一章 极限", "第二章 连续"),
                   expected_revision=0, origin="autosave")
    session.commit()
    return course, book


def test_outline_is_built_from_document_headings(client, session):
    course, book = _ready_book(session)
    outline = client.get(f"/api/v1/courses/{course.id}/notebooks/{book.id}")
    assert outline.status_code == 200
    body = outline.json()
    assert [chapter["title"] for chapter in body["chapters"]] == ["第一章 极限", "第二章 连续"]
    assert body["chapters"][0]["sections"][0]["title"] == "第一章 极限"
    assert body["historical_sections"] == []
    sections = client.get(f"/api/v1/courses/{course.id}/notebooks/{book.id}/sections")
    assert sections.status_code == 200
    assert {row["heading"] for row in sections.json()} == {"第一章 极限", "第二章 连续"}


def test_reading_position_uses_block_id(client, session):
    course, book = _ready_book(session)
    url = f"/api/v1/courses/{course.id}/notebooks/{book.id}/reading-position"
    saved = client.put(url, json={
        "mode": "book", "section_offset": 0.2, "expected_revision": 0,
        "block_id": "h-2",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["block_id"] == "h-2"
    missing = client.put(url, json={
        "mode": "book", "section_offset": 0.2, "expected_revision": 1,
        "block_id": "missing-block",
    })
    assert missing.status_code == 404


def test_course_tree_and_overview_use_body(client, session):
    course, _book = _ready_book(session)
    tree = client.get(f"/api/v1/forest/courses/{course.id}/tree")
    assert tree.status_code == 200
    assert tree.json()["notebooks"][0]["chapters"][0]["title"] == "第一章 极限"
    overview = client.get(f"/api/v1/courses/{course.id}/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["notebooks"] == 1
    assert overview.json()["counts"]["sections"] == 2
    assert overview.json()["materials"][0]["generation_allowed"] is True


def test_knowledge_graph_tracks_document_edits_and_history_restore(client, session):
    course, book = _ready_book(session)
    graph_url = f"/api/v1/courses/{course.id}/knowledge-graph"
    graph = client.get(graph_url)
    assert graph.status_code == 200
    assert {node["name"] for node in graph.json()["nodes"]} == {"第一章 极限", "第二章 连续"}

    changed = client.put(
        f"/api/v1/courses/{course.id}/notebooks/{book.id}/document",
        json={"content": _document("第三章 导数"), "expected_revision": 1},
    )
    assert changed.status_code == 200, changed.text
    edited_graph = client.get(graph_url).json()
    assert [node["name"] for node in edited_graph["nodes"]] == ["第三章 导数"]
    assert [node["id"] for node in edited_graph["nodes"]] == ["h-1"]

    restored = client.post(
        f"/api/v1/courses/{course.id}/notebooks/{book.id}/revisions/1/restore",
        json={"expected_revision": 2},
    )
    assert restored.status_code == 200, restored.text
    restored_graph = client.get(graph_url).json()
    assert [node["name"] for node in restored_graph["nodes"]] == ["第一章 极限", "第二章 连续"]
    assert {node["revision"] for node in restored_graph["nodes"]} == {3}


def test_forest_relations_between_notebooks(client, session):
    _course_a, book_a = _ready_book(session, title="A 笔记", course_name="课程 A")
    _course_b, book_b = _ready_book(session, title="B 笔记", course_name="课程 B")
    created = client.post("/api/v1/forest/relations", json={
        "source_notebook_id": book_a.id, "target_notebook_id": book_b.id,
        "relation_type": "prerequisite", "reason": "先学极限再学连续",
    })
    assert created.status_code == 201, created.text
    relation = created.json()
    assert relation["source_title"] == "A 笔记"
    assert relation["target_course_name"] == "课程 B"
    duplicate = client.post("/api/v1/forest/relations", json={
        "source_notebook_id": book_a.id, "target_notebook_id": book_b.id,
        "relation_type": "prerequisite", "reason": "重复",
    })
    assert duplicate.status_code == 409
    same_course = client.post("/api/v1/forest/relations", json={
        "source_notebook_id": book_a.id, "target_notebook_id": book_a.id,
        "relation_type": "related", "reason": "自连",
    })
    assert same_course.status_code == 422
    listed = client.get("/api/v1/forest/relations")
    assert [row["id"] for row in listed.json()] == [relation["id"]]
    deleted = client.delete(f"/api/v1/forest/relations/{relation['id']}")
    assert deleted.status_code == 200


def test_forest_search_finds_body_text(client, session):
    _course, book = _ready_book(session, title="极限笔记")
    search = client.get("/api/v1/forest/search", params={"q": "正文内容"})
    assert search.status_code == 200
    assert any(item["notebook_id"] == book.id for item in search.json())


def test_bind_and_move_update_section_course_scope(client, session):
    course_a = make_course(session, "课程 A")
    course_b = make_course(session, "课程 B")
    book = make_notebook(session, None, "未分类")
    asset = make_asset(session, book)
    make_material(session, book, asset)
    persist_ir(session, book, asset)
    write_document(session, book, _document("第一章 极限"), expected_revision=0,
                   origin="autosave")
    session.commit()
    bound = client.post(f"/api/v1/notebooks/{book.id}/bind", json={"course_id": course_a.id})
    assert bound.status_code == 200, bound.text
    session.expire_all()
    assert all(row.course_id == course_a.id for row in session.query(NotebookSection).all())
    moved = client.post(f"/api/v1/notebooks/{book.id}/move", json={"course_id": course_b.id})
    assert moved.status_code == 200, moved.text
    session.expire_all()
    assert all(row.course_id == course_b.id for row in session.query(NotebookSection).all())
    tree = client.get(f"/api/v1/courses/{course_b.id}/notebooks")
    assert [row["id"] for row in tree.json()] == [book.id]


def test_course_tree_tracks_generation_without_fake_body_chapters(client, session):
    from app.api.v1.generation import create_generation_job
    from app.db.models import NotebookGenerationJob
    from app.schemas.generation import NotebookGenerationCreate

    course = make_course(session)
    book = make_notebook(session, course)
    asset = make_asset(session, book)
    persist_ir(session, book, asset)
    created = create_generation_job(book.id, NotebookGenerationCreate(asset_ids=[asset.id]),
                                    "tree-pending", session)
    tree = client.get(f"/api/v1/forest/courses/{course.id}/tree").json()
    assert tree["notebooks"][0]["processing"] is True
    assert tree["notebooks"][0]["chapters"] == []
    job = session.get(NotebookGenerationJob, created["id"])
    job.status = "failed"
    session.commit()
    tree = client.get(f"/api/v1/forest/courses/{course.id}/tree").json()
    assert tree["notebooks"][0]["processing"] is False


def test_forest_counts_only_sections_of_live_notebooks(client, session):
    from app.db.models import utc_now

    course, book = _ready_book(session)
    forest = client.get("/api/v1/forest").json()
    assert next(row for row in forest["courses"] if row["course_id"] == course.id)["section_count"] == 2
    book.deleted_at = utc_now()
    session.commit()
    forest = client.get("/api/v1/forest").json()
    row = next(row for row in forest["courses"] if row["course_id"] == course.id)
    assert row["section_count"] == row["note_count"] == row["notebook_count"] == 0


def test_section_relations_use_scoped_anchors_and_require_reconfirmation(client, session):
    from app.db.models import Notebook

    _, book_a = _ready_book(session, title="A 笔记", course_name="课程 A")
    _, book_b = _ready_book(session, title="B 笔记", course_name="课程 B")
    payload = {
        "source_notebook_id": book_a.id, "target_notebook_id": book_b.id,
        "source_block_id": "h-1", "target_block_id": "h-2",
        "relation_type": "prerequisite", "reason": "先理解极限再学习连续",
    }
    response = client.post("/api/v1/forest/relations", json=payload)
    assert response.status_code == 201, response.text
    relation = response.json()
    assert relation["source_block_id"] == "h-1"
    assert relation["target_block_id"] == "h-2"
    assert relation["stale"] is False
    # The same notebooks may contain several different section-level links.
    another = client.post("/api/v1/forest/relations", json={**payload, "target_block_id": "h-1"})
    assert another.status_code == 201, another.text
    assert client.post("/api/v1/forest/relations", json=payload).status_code == 409
    invalid = client.post("/api/v1/forest/relations", json={**payload, "source_block_id": "foreign"})
    assert invalid.status_code == 422

    write_document(session, session.get(Notebook, book_a.id), _document("第一章 极限的修订", "第二章 连续"),
                   expected_revision=1, origin="autosave")
    session.commit()
    rows = client.get("/api/v1/forest/relations").json()
    assert next(row for row in rows if row["id"] == relation["id"])["stale"] is True
    refreshed = client.post(f"/api/v1/forest/relations/{relation['id']}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["stale"] is False
    # Removing the anchor cannot silently reconnect a relation to another block.
    write_document(session, book_a, {"type": "doc", "content": []}, expected_revision=2)
    session.commit()
    assert client.post(f"/api/v1/forest/relations/{relation['id']}/refresh").status_code == 422
