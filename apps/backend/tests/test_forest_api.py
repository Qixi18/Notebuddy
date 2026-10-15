"""Forest profiles and real cross-course note relations preserve user data."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.courses import router as courses_router
from app.api.v1.forest import router
from app.db.database import Base, get_db
from app.db.models import Course, KnowledgeNode, Material, MaterialPage, Note, PageBlock, SourceRef


@pytest.fixture
def forest_setup():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        courses = [Course(id=f"course-{i}", name=name) for i, name in enumerate(["数学", "程序设计", "空课程"])]
        db.add_all(courses)
        db.flush()
        notes, materials, refs = [], [], []
        for i in range(2):
            material = Material(course_id=courses[i].id, lecture_title="第一讲", original_filename=f"{i}.pdf", stored_filename=f"{i}.pdf", size_bytes=1)
            node = KnowledgeNode(course_id=courses[i].id, name=f"概念{i}")
            db.add_all([material, node]); db.flush()
            page = MaterialPage(material_id=material.id, page_number=1, raw_text="真实定义")
            db.add(page); db.flush()
            block = PageBlock(page_id=page.id, block_type="text", content="真实定义", position=0)
            db.add(block); db.flush()
            ref = SourceRef(page_block_id=block.id, quote="真实定义")
            note = Note(id=f"note-{i}", course_id=courses[i].id, knowledge_node_id=node.id, material_id=material.id, title=f"知识小节{i}", content_markdown=f"用户正文{i}", user_locked=True, revision_number=3)
            note.source_refs.append(ref)
            db.add(note)
            notes.append(note); materials.append(material); refs.append(ref)
        db.commit()
        test_app = FastAPI()
        test_app.include_router(router, prefix="/api/v1")
        test_app.include_router(courses_router, prefix="/api/v1")
        test_app.dependency_overrides[get_db] = lambda: db
        yield TestClient(test_app), db, courses, materials, notes, refs
    engine.dispose()


def relation_payload(notes, **changes):
    return {"source_note_id": notes[0].id, "target_note_id": notes[1].id, "relation_type": "related", "reason": "两讲都解释变量与映射", **changes}


def test_new_course_first_material_does_not_start_learning_without_confirmation(forest_setup):
    client, db, *_ = forest_setup
    created = client.post("/api/v1/courses", json={"name": "新课程"})
    assert created.status_code == 201
    course_id = created.json()["id"]
    # The user uploads before ever visiting the forest; upload persistence alone
    # must not change their learning state.
    db.add(Material(course_id=course_id, lecture_title="第一讲", original_filename="first.pdf", stored_filename="first.pdf", size_bytes=1))
    db.commit()
    row = next(row for row in client.get("/api/v1/forest").json()["courses"] if row["course_id"] == course_id)
    assert row["learning_state"] == "planned"
    changed = client.patch(f"/api/v1/forest/courses/{course_id}", json={"expected_revision": row["revision"], "learning_state": "learning"})
    assert changed.status_code == 200
    assert changed.json()["learning_state"] == "learning"


def test_old_courses_initialize_and_keep_manual_state_after_new_upload(forest_setup):
    client, db, courses, _, _, _ = forest_setup
    response = client.get("/api/v1/forest")
    assert response.status_code == 200
    initial = {row["course_id"]: row for row in response.json()["courses"]}
    assert initial[courses[0].id]["learning_state"] == "learning"
    assert initial[courses[2].id]["learning_state"] == "planned"
    assert initial[courses[0].id]["note_count"] == 1
    assert [row["position"] for row in response.json()["courses"]] == [0, 1, 2]
    update = client.patch(f"/api/v1/forest/courses/{courses[0].id}", json={"expected_revision": 0, "learning_state": "completed", "semester": 2, "position": 7, "level": "foundation", "prerequisites": ["先修数学"]})
    assert update.status_code == 200
    assert update.json()["revision"] == 1
    db.add(Material(course_id=courses[0].id, lecture_title="新讲", original_filename="new.pdf", stored_filename="new.pdf", size_bytes=1)); db.commit()
    later = {row["course_id"]: row for row in client.get("/api/v1/forest").json()["courses"]}
    assert later[courses[0].id]["learning_state"] == "completed"
    assert later[courses[0].id]["position"] == 7
    assert later[courses[0].id]["prerequisites"] == ["先修数学"]


def test_profile_stale_revision_conflicts_and_preserves_first_write(forest_setup):
    client, _, courses, _, _, _ = forest_setup
    client.get("/api/v1/forest")
    url = f"/api/v1/forest/courses/{courses[0].id}"
    assert client.patch(url, json={"expected_revision": 0, "semester": 3}).status_code == 200
    assert client.patch(url, json={"expected_revision": 0, "semester": 4}).status_code == 409
    row = next(row for row in client.get("/api/v1/forest").json()["courses"] if row["course_id"] == courses[0].id)
    assert row["semester"] == 3
    assert row["revision"] == 1


def test_manual_relation_uses_two_real_notes_and_sources_without_editing_body(forest_setup):
    client, _, courses, _, notes, refs = forest_setup
    response = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert response.status_code == 201
    row = response.json()
    assert row["status"] == "confirmed" and row["origin"] == "manual"
    assert row["source_course_id"] == courses[0].id and row["target_course_id"] == courses[1].id
    assert row["source_title"] == "知识小节0" and row["target_course_name"] == "程序设计"
    assert row["source_revision"] == 3 and row["target_revision"] == 3 and not row["stale"]
    assert row["source_ref_ids"] == [refs[0].id] and row["target_ref_ids"] == [refs[1].id]
    assert notes[0].content_markdown == "用户正文0" and notes[0].user_locked
    assert client.get("/api/v1/forest/relations").json()[0]["id"] == row["id"]


def test_related_reverse_duplicate_is_rejected_but_directional_relation_is_distinct(forest_setup):
    client, _, _, _, notes, _ = forest_setup
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes)).status_code == 201
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes[::-1])).status_code == 409
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes, relation_type="prerequisite")).status_code == 201
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes[::-1], relation_type="prerequisite")).status_code == 201


def test_invalid_relation_endpoints_and_unverified_sources_are_rejected(forest_setup):
    client, db, _, _, notes, refs = forest_setup
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes, target_note_id="missing")).status_code == 404
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes, target_note_id=notes[0].id)).status_code == 422
    foreign_same = Note(course_id=notes[0].course_id, knowledge_node_id=notes[0].knowledge_node_id, title="同课程第二节", content_markdown="独立正文")
    db.add(foreign_same); db.commit()
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes, target_note_id=foreign_same.id)).status_code == 422
    refs[0].status = "stale"; db.commit()
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes)).status_code == 422


def test_note_edits_and_reparse_evidence_mark_relation_stale_and_block_confirmation(forest_setup):
    client, db, _, _, notes, refs = forest_setup
    created = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert created.status_code == 201
    relation_id = created.json()["id"]
    notes[0].revision_number = 4; db.commit()
    assert client.get("/api/v1/forest/relations").json()[0]["stale"]
    assert client.post(f"/api/v1/forest/relations/{relation_id}/review", json={"decision": "confirm"}).status_code == 409
    notes[0].revision_number = 3; refs[0].status = "stale"; db.commit()
    assert client.get("/api/v1/forest/relations").json()[0]["stale"]
    assert client.post(f"/api/v1/forest/relations/{relation_id}/review", json={"decision": "reject"}).status_code == 200
    assert client.get("/api/v1/forest/relations").json() == []
    assert client.get("/api/v1/forest/relations?status=rejected").json()[0]["id"] == relation_id
    assert client.delete(f"/api/v1/forest/relations/{relation_id}").json() == {"deleted": True}


def test_soft_deleted_course_and_material_hide_and_restore_stable_relations(forest_setup):
    from datetime import UTC, datetime
    client, db, courses, materials, notes, _ = forest_setup
    result = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert result.status_code == 201
    relation_id = result.json()["id"]
    for deleted in (courses[0], materials[0]):
        deleted.deleted_at = datetime.now(UTC); db.commit()
        assert client.get("/api/v1/forest/relations?status=all").json() == []
        deleted.deleted_at = None; db.commit()
        assert client.get("/api/v1/forest/relations").json()[0]["id"] == relation_id
    materials[0].deleted_at = datetime.now(UTC); db.commit()
    row = next(row for row in client.get("/api/v1/forest").json()["courses"] if row["course_id"] == courses[0].id)
    assert row["note_count"] == 0 and row["material_count"] == 0


def test_cross_course_forest_relation_does_not_create_legacy_knowledge_edges(forest_setup):
    from sqlalchemy import select

    from app.db.models import KnowledgeEdge
    client, db, _, _, notes, _ = forest_setup
    result = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert result.status_code == 201
    assert db.scalars(select(KnowledgeEdge)).all() == []


def test_search_finds_hidden_courses_and_historical_sections_without_bodies(forest_setup):
    from datetime import UTC, datetime
    client, db, courses, materials, notes, _ = forest_setup
    historical = Note(course_id=courses[1].id, knowledge_node_id=notes[1].knowledge_node_id, title="历史映射", content_markdown="不可加载的长正文")
    db.add(historical); db.commit()
    response = client.get("/api/v1/forest/search?q=程序设计")
    assert response.status_code == 200
    assert {row["note_id"] for row in response.json()} == {notes[1].id, historical.id}
    assert set(response.json()[0]) == {"course_id", "course_name", "note_id", "title", "material_id", "notebook_id"}
    assert client.get("/api/v1/forest/search?q=历史映射").json()[0]["note_id"] == historical.id
    materials[1].deleted_at = datetime.now(UTC); db.commit()
    assert [row["note_id"] for row in client.get("/api/v1/forest/search?q=程序设计").json()] == [historical.id]
    courses[1].deleted_at = datetime.now(UTC); db.commit()
    assert client.get("/api/v1/forest/search?q=程序设计").json() == []
    assert client.get("/api/v1/forest/search", params={"q": "x" * 201}).status_code == 422


def test_search_limits_real_results_and_treats_wildcards_as_literal(forest_setup):
    client, db, courses, _, notes, _ = forest_setup
    for i in range(41):
        db.add(Note(course_id=courses[0].id, knowledge_node_id=notes[0].knowledge_node_id, title=f"查找{i}", content_markdown="正文"))
    db.add(Note(course_id=courses[0].id, knowledge_node_id=notes[0].knowledge_node_id, title="比例100%", content_markdown="正文"))
    db.commit()
    response = client.get("/api/v1/forest/search?q=查找")
    assert response.status_code == 200
    assert len(response.json()) == 40
    assert [row["title"] for row in client.get("/api/v1/forest/search", params={"q": "%"}).json()] == ["比例100%"]


def test_profile_concurrency_rejects_writer_with_preloaded_old_snapshot(tmp_path):
    from app.db.models import ForestCourseProfile
    from app.forest.service import ForestConflict, update_profile
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.add(Course(id="c", name="课程")); seed.flush()
        seed.add(ForestCourseProfile(course_id="c", position=0)); seed.commit()
    with Session(engine, expire_on_commit=False) as first, Session(engine, expire_on_commit=False) as second:
        first_course, second_course = first.get(Course, "c"), second.get(Course, "c")
        stale = second.get(ForestCourseProfile, "c")
        second.commit()
        update_profile(first, first_course, expected_revision=0, changes={"semester": 2}); first.commit()
        assert stale.revision == 0
        with pytest.raises(ForestConflict):
            update_profile(second, second_course, expected_revision=0, changes={"semester": 3})
        second.rollback()
    with Session(engine) as verify:
        assert verify.get(ForestCourseProfile, "c").semester == 2
    engine.dispose()


def test_manual_reconnect_refreshes_stale_relation_without_replacing_note_identity(forest_setup):
    client, db, _, _, notes, _ = forest_setup
    created = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert created.status_code == 201
    relation_id = created.json()["id"]
    notes[0].revision_number = 4
    notes[0].content_markdown = "用户手工补充的正文"; db.commit()
    assert client.get("/api/v1/forest/relations").json()[0]["stale"]
    assert client.post(f"/api/v1/forest/relations/{relation_id}/review", json={"decision": "confirm"}).status_code == 409
    reconnected = client.post("/api/v1/forest/relations", json=relation_payload(notes, reason="编辑后重新核对的关联依据"))
    assert reconnected.status_code == 201
    assert reconnected.json()["id"] == relation_id
    assert reconnected.json()["source_revision"] == 4
    assert not reconnected.json()["stale"]
    assert reconnected.json()["reason"] == "编辑后重新核对的关联依据"
    assert reconnected.json()["status"] == "confirmed" and reconnected.json()["origin"] == "manual"
    assert notes[0].content_markdown == "用户手工补充的正文" and notes[0].user_locked
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes)).status_code == 409


@pytest.mark.parametrize("invalid", ["forged_quote", "foreign_material", "inactive_page"])
def test_relation_rejects_sources_that_cannot_verify_the_note(forest_setup, invalid):
    client, db, _, _, notes, refs = forest_setup
    if invalid == "forged_quote":
        refs[0].quote = "原始块从未出现的描述"
    elif invalid == "foreign_material":
        notes[0].source_refs = [refs[1]]
    else:
        refs[0].page_block.page.is_active = False
    db.commit()
    assert client.post("/api/v1/forest/relations", json=relation_payload(notes)).status_code == 422


def test_historical_relation_is_hidden_when_its_only_source_material_is_removed(forest_setup):
    from datetime import UTC, datetime
    client, db, _, materials, notes, _ = forest_setup
    notes[0].material_id = None; db.commit()
    created = client.post("/api/v1/forest/relations", json=relation_payload(notes))
    assert created.status_code == 201
    relation_id = created.json()["id"]
    materials[0].deleted_at = datetime.now(UTC); db.commit()
    assert client.get("/api/v1/forest/relations?status=all").json() == []
    assert client.get("/api/v1/forest/search?q=知识小节0").json() == []
    materials[0].deleted_at = None; db.commit()
    assert client.get("/api/v1/forest/relations").json()[0]["id"] == relation_id
