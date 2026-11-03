from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import app
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _doc(title: str) -> dict:
    return {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 1, "blockId": "heading"},
         "content": [{"type": "text", "text": title}]},
        {"type": "paragraph", "attrs": {"blockId": "body"},
         "content": [{"type": "text", "text": f"{title} 的正文"}]},
    ]}


def test_forest_relation_visibility_tracks_bind_move_and_unbind(client, session):
    from app.notes.store import write_document

    source_course = make_course(session, "来源课程")
    target_course = make_course(session, "目标课程")
    source = make_notebook(session, source_course, "来源笔记")
    target = make_notebook(session, target_course, "目标笔记")
    write_document(session, source, _doc("来源章节"), expected_revision=0, origin="autosave")
    write_document(session, target, _doc("目标章节"), expected_revision=0, origin="autosave")
    session.commit()

    created = client.post("/api/v1/forest/relations", json={
        "source_notebook_id": source.id,
        "target_notebook_id": target.id,
        "source_block_id": "heading",
        "target_block_id": "heading",
        "relation_type": "related",
        "reason": "共享主题",
    })
    assert created.status_code == 201, created.text
    relation_id = created.json()["id"]
    assert len(client.get("/api/v1/forest/relations").json()) == 1

    moved = client.post(f"/api/v1/notebooks/{target.id}/move", json={"course_id": source_course.id})
    assert moved.status_code == 200, moved.text
    assert client.get("/api/v1/forest/relations").json() == []

    unbound = client.post(f"/api/v1/notebooks/{target.id}/unbind")
    assert unbound.status_code == 200, unbound.text
    assert client.get("/api/v1/forest/relations").json() == []

    rebound = client.post(f"/api/v1/notebooks/{target.id}/bind", json={"course_id": target_course.id})
    assert rebound.status_code == 200, rebound.text
    visible = client.get("/api/v1/forest/relations").json()
    assert [row["id"] for row in visible] == [relation_id]
    assert visible[0]["stale"] is False


def test_bulk_move_hides_relations_with_same_course_and_restores_them(client, session, monkeypatch):
    from app.forest.notebook_relations import enqueue_notebook_relations
    from app.notes.store import write_document

    first_course = make_course(session, "第一门课程")
    second_course = make_course(session, "第二门课程")
    source = make_notebook(session, first_course, "来源笔记")
    target = make_notebook(session, second_course, "目标笔记")
    write_document(session, source, _doc("来源章节"), expected_revision=0, origin="autosave")
    write_document(session, target, _doc("目标章节"), expected_revision=0, origin="autosave")
    session.commit()
    relation = client.post("/api/v1/forest/relations", json={
        "source_notebook_id": source.id,
        "target_notebook_id": target.id,
        "source_block_id": "heading",
        "target_block_id": "heading",
        "relation_type": "related",
        "reason": "共享主题",
    })
    assert relation.status_code == 201, relation.text
    relation_id = relation.json()["id"]

    monkeypatch.setattr(
        "app.forest.notebook_relations.enqueue_notebook_relations",
        lambda *_args, **_kwargs: None,
    )
    moved = client.post("/api/v1/notebooks/bulk-manage", json={
        "notebook_ids": [target.id], "action": "move", "course_id": first_course.id,
    })
    assert moved.status_code == 200, moved.text
    assert client.get("/api/v1/forest/relations").json() == []

    monkeypatch.setattr(
        "app.forest.notebook_relations.enqueue_notebook_relations",
        enqueue_notebook_relations,
    )
    restored = client.post(f"/api/v1/notebooks/{target.id}/move", json={
        "course_id": second_course.id,
    })
    assert restored.status_code == 200, restored.text
    visible = client.get("/api/v1/forest/relations").json()
    assert [row["id"] for row in visible] == [relation_id]
    assert visible[0]["stale"] is False
