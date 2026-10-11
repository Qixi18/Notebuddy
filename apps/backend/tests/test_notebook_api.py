import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import Course, KnowledgeNode, Material, Note
from app.main import app


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        course, other = Course(name="课程"), Course(name="另课")
        db.add_all([course, other])
        db.flush()
        materials = [Material(course_id=course.id, lecture_title=f"讲{i}", chapter_order=i,
                     original_filename="a.pptx", stored_filename=f"{i}.pptx", size_bytes=1)
                     for i in (0, 1)]
        foreign = Material(course_id=other.id, lecture_title="别讲", original_filename="b.pptx", stored_filename="b.pptx", size_bytes=1)
        node = KnowledgeNode(course_id=course.id, name="重复概念")
        db.add_all([*materials, foreign, node])
        db.flush()
        notes = [Note(course_id=course.id, knowledge_node_id=node.id, material_id=m.id,
                      section_key="slide:1", section_order=1, title=f"小节{i}", content_markdown=f"正文{i}")
                 for i, m in enumerate(materials)]
        legacy = Note(course_id=course.id, knowledge_node_id=node.id, title="历史", content_markdown="旧正文")
        db.add_all([*notes, legacy])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), db, course, materials, notes, legacy, foreign
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_notebook_outline_chapter_and_occurrences(setup):
    client, _, course, materials, notes, legacy, foreign = setup
    outline = client.get(f"/api/v1/courses/{course.id}/notebook")
    assert outline.status_code == 200
    body = outline.json()
    assert [c["id"] for c in body["chapters"]] == [m.id for m in materials]
    assert body["chapters"][1]["sections"][0]["id"] == notes[1].id
    assert "content_markdown" not in body["chapters"][0]["sections"][0]
    assert body["historical_sections"][0]["id"] == legacy.id
    chapter = client.get(f"/api/v1/courses/{course.id}/notebook/chapters/{materials[1].id}")
    assert chapter.json()["sections"][0]["content_markdown"] == "正文1"
    assert client.get(f"/api/v1/courses/{course.id}/notebook/chapters/{foreign.id}").status_code == 404
    occurrences = client.get(f"/api/v1/courses/{course.id}/knowledge-graph").json()["occurrences"]
    assert {o["id"] for o in occurrences} == {n.id for n in notes} | {legacy.id}


def test_order_validation_and_stale_revision(setup):
    client, _, course, materials, _, _, foreign = setup
    url = f"/api/v1/courses/{course.id}/notebook/order"
    ids = [m.id for m in materials]
    for invalid in ([ids[0]], [ids[0], ids[0]], [ids[0], foreign.id]):
        assert client.patch(url, json={"material_ids": invalid, "expected_order_revision": 0}).status_code == 422
    result = client.patch(url, json={"material_ids": ids[::-1], "expected_order_revision": 0})
    assert result.status_code == 200
    assert result.json()["order_revision"] == 1
    assert [c["id"] for c in result.json()["chapters"]] == ids[::-1]
    assert client.patch(url, json={"material_ids": ids, "expected_order_revision": 0}).status_code == 409


def test_removed_chapter_preserves_notes_and_invalidates_order(setup, monkeypatch):
    client, db, course, materials, notes, _, _ = setup
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    assert client.delete(f"/api/v1/materials/{materials[0].id}").status_code == 200
    outline = client.get(f"/api/v1/courses/{course.id}/notebook").json()
    assert outline["order_revision"] == 1
    assert outline["removed_chapters"][0]["sections"][0]["id"] == notes[0].id
    assert db.get(Note, notes[0].id).content_markdown == "正文0"
    assert client.post(f"/api/v1/materials/{materials[0].id}/restore").status_code == 200
    assert client.get(f"/api/v1/courses/{course.id}/notebook").json()["order_revision"] == 2


def test_upload_appends_chapter_and_invalidates_old_order(setup, monkeypatch, tmp_path):
    from io import BytesIO

    from pypdf import PdfWriter

    from app.core.config import settings
    client, _, course, materials, _, _, _ = setup
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    writer = PdfWriter(); writer.add_blank_page(width=72, height=72)
    source = BytesIO(); writer.write(source)
    response = client.post(f"/api/v1/courses/{course.id}/materials",
                           files={"file": ("new.pdf", source.getvalue(), "application/pdf")},
                           data={"lecture_title": "新讲"})
    assert response.status_code == 201
    outline = client.get(f"/api/v1/courses/{course.id}/notebook").json()
    assert outline["order_revision"] == 1
    assert outline["chapters"][-1]["title"] == "新讲"
    assert client.patch(f"/api/v1/courses/{course.id}/notebook/order", json={
        "material_ids": [m.id for m in materials], "expected_order_revision": 0
    }).status_code == 409


def test_web_sources_only_follow_the_notes_lecture(setup):
    from app.db.models import WebSource
    client, db, course, materials, notes, _, _ = setup
    for i, material in enumerate(materials):
        db.add(WebSource(course_id=course.id, material_id=material.id,
                         knowledge_node_id=notes[0].knowledge_node_id, title=f"来源{i}",
                         url=f"https://example.org/{i}", site_name="示例", search_query="矩阵"))
    db.commit()
    result = client.get(f"/api/v1/notes/{notes[1].id}/web-sources")
    assert [source["title"] for source in result.json()] == ["来源1"]


def test_historical_web_sources_follow_actual_note_materials(setup):
    from app.db.models import MaterialPage, PageBlock, SourceRef, WebSource
    client, db, course, materials, notes, legacy, _ = setup
    unrelated = Material(course_id=course.id, lecture_title="第三讲", original_filename="c.pptx",
                         stored_filename="c.pptx", size_bytes=1)
    db.add(unrelated); db.flush()
    for i, material in enumerate([*materials, unrelated]):
        db.add(WebSource(course_id=course.id, material_id=material.id,
                         knowledge_node_id=notes[0].knowledge_node_id, title=f"来源{i}",
                         url=f"https://example.org/{i}", site_name="示例", search_query="矩阵"))
        if material in materials:
            page = MaterialPage(material_id=material.id, page_number=1, raw_text="旧正文来源")
            db.add(page); db.flush()
            block = PageBlock(page_id=page.id, block_type="text", content="原文", position=0)
            db.add(block); db.flush()
            source = SourceRef(page_block_id=block.id, source_type="course_material", quote="原文")
            db.add(source); db.flush()
            legacy.source_refs.append(source)
    db.commit()
    result = client.get(f"/api/v1/notes/{legacy.id}/web-sources")
    assert {source["title"] for source in result.json()} == {"来源0", "来源1"}
