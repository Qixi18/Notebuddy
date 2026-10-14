from io import BytesIO

from pypdf import PdfWriter

pytest_plugins = ["tests.test_notebook_api"]


def create_book(client, course, title):
    response = client.post(f"/api/v1/courses/{course.id}/notebooks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_books_isolate_same_named_notes_and_legacy_default(setup):
    client, db, course, materials, notes, legacy, foreign = setup
    root = f"/api/v1/courses/{course.id}"
    original = client.get(root + "/notebook").json()
    second = create_book(client, course, "同名")
    third = create_book(client, course, "同名")
    assert second["id"] != third["id"]
    books = client.get(root + "/notebooks").json()
    assert len(books) == 3
    assert len({b["tree_slot"] for b in books}) == 3
    outline = client.get(root + f"/notebooks/{second['id']}").json()
    assert outline["chapters"] == [] and outline["historical_sections"] == []
    assert client.get(root + f"/notebooks/{second['id']}/chapters/{materials[0].id}").status_code == 404
    assert client.get(root + "/notebook").json()["id"] == original["id"]
    tree = client.get(f"/api/v1/forest/courses/{course.id}/tree").json()
    assert tree["course_id"] == course.id and len(tree["notebooks"]) == 3
    section = tree["notebooks"][0]["chapters"][0]["sections"][0]
    assert section["notebook_id"] == original["id"] and section["tree_slot"] >= 0
    assert "content_markdown" not in section
    assert len({n.tree_slot for n in [*notes, legacy]}) == 3
    assert db.get(type(legacy), legacy.id).content_markdown == "旧正文"
    assert client.get(f"/api/v1/courses/{foreign.course_id}/notebooks/{second['id']}").status_code == 404


def test_reading_position_ownership_revision_and_visit(setup):
    client, _, course, materials, notes, _, _ = setup
    root = f"/api/v1/courses/{course.id}"
    original = client.get(root + "/notebook").json()
    second = create_book(client, course, "第二本")
    url = root + f"/notebooks/{original['id']}/reading-position"
    assert client.get(url).json() is None
    payload = {"chapter_id": materials[0].id, "note_id": notes[0].id,
               "mode": "chapter", "section_offset": 0.42, "expected_revision": 0}
    result = client.put(url, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == 1
    assert client.get(url).json()["section_offset"] == 0.42
    assert client.put(url, json=payload).status_code == 409
    assert client.put(root + f"/notebooks/{second['id']}/reading-position", json=payload).status_code == 404
    assert client.put(url, json={**payload, "section_offset": 1.1}).status_code == 422
    assert client.get("/api/v1/courses").json()[0]["last_opened_at"] is None
    visit = client.post(root + "/visit")
    assert visit.status_code == 200 and visit.json()["last_opened_at"]
    assert next(c for c in client.get("/api/v1/courses").json() if c["id"] == course.id)["last_opened_at"]


def test_upload_duplicates_and_idempotency_scoped_to_book(setup, monkeypatch, tmp_path):
    from app.core.config import settings

    client, _, course, _, _, _, _ = setup
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    root = f"/api/v1/courses/{course.id}"
    first = client.get(root + "/notebook").json()
    second = create_book(client, course, "第二本")
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    source = BytesIO()
    writer.write(source)

    def upload(book=None, key=None):
        return client.post(root + "/materials",
                           files={"file": ("a.pdf", source.getvalue(), "application/pdf")},
                           data={"lecture_title": "同名讲", **({"notebook_id": book} if book else {})},
                           headers={"Idempotency-Key": key} if key else {})

    assert upload().status_code == 422
    a = upload(first["id"], "request")
    assert a.status_code == 201, a.text
    assert upload(first["id"]).status_code == 409
    assert upload(first["id"], "request").json()["material"]["id"] == a.json()["material"]["id"]
    b = upload(second["id"], "request")
    assert b.status_code == 201 and b.json()["material"]["id"] != a.json()["material"]["id"]
    assert b.json()["material"]["notebook_id"] == second["id"]
    outline = client.get(root + f"/notebooks/{second['id']}").json()
    assert len(outline["chapters"]) == 1 and outline["order_revision"] == 1


def test_empty_course_reads_do_not_create_book(setup):
    client, _, _, _, _, _, _ = setup
    course = client.post("/api/v1/courses", json={"name": "空课"}).json()
    root = f"/api/v1/courses/{course['id']}"
    assert client.get(root + "/notebooks").json() == []
    assert client.get(root + "/notebook").status_code == 404
    assert client.get(f"/api/v1/forest/courses/{course['id']}/tree").json()["notebooks"] == []


def test_note_slots_are_monotonic_after_last_note_deleted(setup):
    from app.db.models import Note

    _, db, course, _, notes, legacy, _ = setup
    last = max([*notes, legacy], key=lambda note: note.tree_slot)
    slot = last.tree_slot
    book_id = last.notebook_id
    db.delete(last)
    db.commit()
    replacement = Note(course_id=course.id, notebook_id=book_id, knowledge_node_id=notes[0].knowledge_node_id,
                       title="新增", content_markdown="正文")
    db.add(replacement)
    db.commit()
    assert replacement.tree_slot > slot


def test_named_order_is_scoped_and_removed_bookmark_stays_in_original_book(setup, monkeypatch):
    client, _, course, materials, notes, _, _ = setup
    root = f"/api/v1/courses/{course.id}"
    original = client.get(root + "/notebook").json()
    second = create_book(client, course, "第二本")
    order = root + f"/notebooks/{second['id']}/order"
    assert client.patch(order, json={"material_ids": [materials[0].id], "expected_order_revision": 0}).status_code == 422
    assert client.patch(order, json={"material_ids": [], "expected_order_revision": 0}).status_code == 200
    assert client.get(root + "/notebook").json()["order_revision"] == original["order_revision"]
    url = root + f"/notebooks/{original['id']}/reading-position"
    assert client.put(url, json={"chapter_id": materials[0].id, "note_id": notes[0].id, "mode": "chapter",
                                 "section_offset": 0.5, "expected_revision": 0}).status_code == 200
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    assert client.delete(f"/api/v1/materials/{materials[0].id}").status_code == 200
    assert client.get(url).json()["note_id"] == notes[0].id
    assert client.get(root + f"/notebooks/{second['id']}/reading-position").json() is None
    assert client.post(f"/api/v1/materials/{materials[0].id}/restore").json()["notebook_id"] == original["id"]
    restored = client.get(root + "/notebook").json()["chapters"][0]["sections"][0]
    assert restored["tree_slot"] == notes[0].tree_slot


def test_legacy_generation_does_not_reuse_other_book_historical_note(setup):
    from app.db.models import KnowledgeNode, Note
    from app.knowledge.extractor import ensure_note

    client, db, course, _, _, _, _ = setup
    second = create_book(client, course, "第二本")
    node = KnowledgeNode(course_id=course.id, name="历史同名")
    db.add(node)
    db.flush()
    other = Note(course_id=course.id, notebook_id=second["id"], knowledge_node_id=node.id,
                 title="历史同名", content_markdown="其他本用户正文", user_locked=True)
    db.add(other)
    db.commit()
    generated = ensure_note(db, course.id, node, "新默认正文", [])
    assert generated.id != other.id
    assert generated.notebook_id == client.get(f"/api/v1/courses/{course.id}/notebook").json()["id"]
    assert other.content_markdown == "其他本用户正文"


def test_three_books_generate_independent_same_concept_and_protect_reparse(setup, monkeypatch):
    from sqlalchemy import select

    from app.db.models import Material, MaterialPage, Note, NoteSuggestion, PageBlock
    from app.knowledge.extractor import extract_material_knowledge
    from app.notes.service import update_note_as_user

    client, db, course, _, _, _, _ = setup
    root = f"/api/v1/courses/{course.id}"
    books = [client.get(root + "/notebook").json(), create_book(client, course, "二"), create_book(client, course, "三")]
    monkeypatch.setattr("app.knowledge.extractor.extract_page_draft",
                        lambda title, text, **kwargs: {"title": "共同概念", "summary": text})
    generated = []
    for i, book in enumerate(books):
        material = Material(course_id=course.id, notebook_id=book["id"], lecture_title=f"讲{i}",
                            original_filename="a.pdf", stored_filename=f"m{i}.pdf", size_bytes=1)
        db.add(material)
        db.flush()
        page = MaterialPage(material_id=material.id, page_number=1, title="共同概念", raw_text=f"正文{i}",
                            stable_location_key="page:1")
        db.add(page)
        db.flush()
        db.add(PageBlock(page_id=page.id, block_type="text", content=f"来源{i}", position=0))
        db.flush()
        extract_material_knowledge(db, material.id)
        db.flush()
        note = db.scalar(select(Note).where(Note.material_id == material.id))
        assert note.notebook_id == book["id"] and f"正文{i}" in note.content_markdown
        generated.append((material, page, note))
    assert len({note.id for _, _, note in generated}) == 3
    assert len({note.knowledge_node_id for _, _, note in generated}) == 1
    material, page, first = generated[0]
    identity, slot = first.id, first.tree_slot
    update_note_as_user(db, first, "用户修改：保留", 1)
    page.raw_text = "重解析草稿"
    extract_material_knowledge(db, material.id)
    db.flush()
    assert first.id == identity and first.tree_slot == slot
    assert first.content_markdown == "用户修改：保留" and first.user_locked
    assert db.scalar(select(NoteSuggestion).where(NoteSuggestion.note_id == first.id)) is not None
    assert "正文1" in generated[1][2].content_markdown
