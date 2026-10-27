import base64
import copy
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    Course,
    Notebook,
    NotebookAttachment,
    NotebookDocumentRevision,
    utc_now,
)
from app.main import app
from app.notes.attachments import (
    prune_deleted_notebook_directories,
    prune_stray_attachment_files,
    prune_unreferenced_attachments,
)
from app.notes.history import record_snapshot

# A real 1x1 PNG: attachment validation rejects header-only placeholders.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def setup():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        course = Course(name="课程")
        db.add(course)
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), db, course
        finally:
            app.dependency_overrides.pop(get_db, None)



def make_book(client, course, title="文档测试"):
    response = client.post(f"/api/v1/courses/{course.id}/notebooks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def document_url(course, book):
    return f"/api/v1/courses/{course.id}/notebooks/{book['id']}/document"


def test_legacy_blocks_are_converted_without_losing_structure(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    blocks = [
        {"id": "source-note-1", "type": "h2", "text": "来源小节"},
        {"id": "body-1", "type": "p", "text": "第一段 **加粗** 与 $F = ma$\n\n- 要点一\n- 要点二"},
    ]
    saved = client.put(url, json={"blocks": blocks, "expected_revision": 0})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["schema_version"] == 2
    assert body["revision"] == 1
    content = body["content"]
    assert content["type"] == "doc"
    assert content["content"][0]["attrs"]["blockId"] == "source-note-1"
    paragraph_text = content["content"][1]["content"]
    assert any(node.get("marks") == [{"type": "bold"}] for node in paragraph_text)
    assert any(node.get("type") == "inlineMath" for node in paragraph_text)
    assert content["content"][2]["type"] == "bulletList"

    reopened = client.get(url).json()
    assert reopened["content"] == content
    assert reopened["blocks"][0] == {"id": "source-note-1", "type": "h2", "text": "来源小节"}
    assert any(block["type"] == "bullet" for block in reopened["blocks"])


def test_v2_document_round_trips_marks_and_stable_ids(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    content = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 1, "blockId": "h-1"},
             "content": [{"type": "text", "text": "物理学"}]},
            {"type": "paragraph", "attrs": {"blockId": "p-1"}, "content": [
                {"type": "text", "text": "基本概念", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "与 "},
                {"type": "text", "text": "链接", "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}]},
            ]},
            {"type": "callout", "attrs": {"blockId": "c-1", "tone": "tip", "title": "重点提示"},
             "content": [{"type": "paragraph", "content": [{"type": "text", "text": "先理解再记忆"}]}]},
        ],
    }
    response = client.put(url, json={"schema_version": 2, "content": content, "expected_revision": 0})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert response.json()["content"] == content
    assert client.get(url).json()["content"] == content
    assert client.put(url, json={"schema_version": 2, "content": content, "expected_revision": 0}).status_code == 409
    assert client.put(url, json={"blocks": [{"id": "h-1", "type": "h1", "text": "旧版覆盖"}],
                                 "expected_revision": 1}).status_code == 409
    assert client.get(url).json()["content"] == content

    blocks = client.get(url).json()["blocks"]
    assert blocks[0]["id"] == "h-1"
    assert "先理解再记忆" in blocks[-1]["text"]


def test_v2_document_rejects_unsafe_or_unknown_nodes(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    base = {"type": "doc", "content": [{"type": "paragraph", "attrs": {"blockId": "p"},
                                        "content": [{"type": "text", "text": "正文"}]}]}

    external_image = copy.deepcopy(base)
    external_image["content"].append({"type": "image", "attrs": {
        "src": "https://example.com/a.png", "attachmentId": "a"}})
    assert client.put(url, json={"schema_version": 2, "content": external_image,
                                 "expected_revision": 0}).status_code == 422

    unknown = copy.deepcopy(base)
    unknown["content"].append({"type": "script", "content": []})
    assert client.put(url, json={"schema_version": 2, "content": unknown,
                                 "expected_revision": 0}).status_code == 422

    nested_heading = copy.deepcopy(base)
    nested_heading["content"][0]["content"] = [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "非法嵌套"}]},
    ]
    assert client.put(url, json={"schema_version": 2, "content": nested_heading,
                                 "expected_revision": 0}).status_code == 422

    malformed_table = {"type": "doc", "content": [{"type": "table", "content": [
        {"type": "text", "text": "不是表格行"},
    ]}]}
    assert client.put(url, json={"schema_version": 2, "content": malformed_table,
                                 "expected_revision": 0}).status_code == 422

    bad_link = copy.deepcopy(base)
    bad_link["content"][0]["content"][0]["marks"] = [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]
    assert client.put(url, json={"schema_version": 2, "content": bad_link,
                                 "expected_revision": 0}).status_code == 422

    deep = {"type": "doc", "content": []}
    node = {"type": "paragraph", "content": [{"type": "text", "text": "x"}]}
    for _ in range(14):
        node = {"type": "blockquote", "content": [node]}
    deep["content"] = [node]
    assert client.put(url, json={"schema_version": 2, "content": deep,
                                 "expected_revision": 0}).status_code == 422
    assert client.get(url).json()["revision"] == 0


def test_missing_block_ids_are_filled_but_duplicates_are_replaced(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "一"}]},
        {"type": "paragraph", "attrs": {"blockId": "same"}, "content": [{"type": "text", "text": "二"}]},
        {"type": "paragraph", "attrs": {"blockId": "same"}, "content": [{"type": "text", "text": "三"}]},
    ]}
    response = client.put(url, json={"schema_version": 2, "content": content, "expected_revision": 0})
    assert response.status_code == 200, response.text
    ids = [node["attrs"]["blockId"] for node in response.json()["content"]["content"]]
    assert len(ids) == len(set(ids)) == 3


def test_legacy_empty_document_and_corrupt_payload_read_as_empty(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    assert client.get(url).json()["content"] == {"type": "doc", "content": []}
    assert client.get(url).json()["blocks"] == []

    saved = client.put(url, json={"blocks": [], "expected_revision": 0})
    assert saved.status_code == 200
    assert saved.json()["content"] == {"type": "doc", "content": []}


def test_document_history_lists_and_restores_as_new_revision(setup):
    client, _, course = setup
    book = make_book(client, course)
    url = document_url(course, book)
    first = [{"id": "h", "type": "h1", "text": "第一版标题"}]
    assert client.put(url, json={"blocks": first, "expected_revision": 0}).status_code == 200
    second_content = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 1, "blockId": "h"}, "content": [{"type": "text", "text": "第二版标题"}]},
    ]}
    assert client.put(url, json={"schema_version": 2, "content": second_content,
                                 "expected_revision": 1}).status_code == 200

    revisions = client.get(f"{url.rsplit('/document', 1)[0]}/revisions")
    assert revisions.status_code == 200
    rows = revisions.json()
    assert [row["revision"] for row in rows] == [2, 1]
    assert rows[0]["origin"] == "autosave"

    snapshot = client.get(f"/api/v1/courses/{course.id}/notebooks/{book['id']}/revisions/1")
    assert snapshot.status_code == 200
    assert snapshot.json()["content"]["content"][0]["content"][0]["text"] == "第一版标题"

    restored = client.post(
        f"/api/v1/courses/{course.id}/notebooks/{book['id']}/revisions/1/restore",
        json={"expected_revision": 2},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == 3
    assert restored.json()["content"] == snapshot.json()["content"]
    assert client.get(url).json()["content"] == snapshot.json()["content"]
    assert client.post(
        f"/api/v1/courses/{course.id}/notebooks/{book['id']}/revisions/1/restore",
        json={"expected_revision": 2},
    ).status_code == 409
    assert client.get(f"/api/v1/courses/{course.id}/notebooks/{book['id']}/revisions/999").status_code == 404


def test_attachment_upload_serves_image_and_rejects_cross_notebook_use(setup, monkeypatch, tmp_path):
    client, _, course = setup
    monkeypatch.setattr("app.core.config.settings.data_dir", tmp_path)
    first = make_book(client, course, "附件本")
    second = make_book(client, course, "另一本")
    png = PNG_1PX
    uploaded = client.post(
        f"/api/v1/courses/{course.id}/notebooks/{first['id']}/attachments",
        files={"file": ("figure.png", png, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mime"] == "image/png" and body["size_bytes"] == len(png)
    served = client.get(body["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == png

    document = {"type": "doc", "content": [
        {"type": "image", "attrs": {"src": body["url"], "attachmentId": body["id"], "alt": "图 1"}},
    ]}
    saved = client.put(document_url(course, first), json={
        "schema_version": 2, "content": document, "expected_revision": 0,
    })
    assert saved.status_code == 200, saved.text
    assert client.put(document_url(course, second), json={
        "schema_version": 2, "content": document, "expected_revision": 0,
    }).status_code == 422

    rejected = client.post(
        f"/api/v1/courses/{course.id}/notebooks/{first['id']}/attachments",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert rejected.status_code == 422
    assert client.get("/api/v1/notebook-attachments/missing").status_code == 404


def test_history_prunes_by_count_and_age(setup):
    client, db, course = setup
    book = make_book(client, course)
    empty = {"type": "doc", "content": []}
    for revision in range(1, 102):
        record_snapshot(db, book["id"], revision, empty)
    revisions = db.scalars(select(NotebookDocumentRevision.revision).where(
        NotebookDocumentRevision.notebook_id == book["id"],
    ).order_by(NotebookDocumentRevision.revision)).all()
    assert revisions == list(range(2, 102))

    db.execute(update(NotebookDocumentRevision).where(
        NotebookDocumentRevision.notebook_id == book["id"],
        NotebookDocumentRevision.revision == 50,
    ).values(created_at=utc_now() - timedelta(days=91)))
    record_snapshot(db, book["id"], 102, empty)
    revisions = db.scalars(select(NotebookDocumentRevision.revision).where(
        NotebookDocumentRevision.notebook_id == book["id"],
    )).all()
    assert 50 not in revisions
    assert len(revisions) == 99


def test_attachment_cleanup_removes_aged_orphans_but_preserves_history(setup, monkeypatch, tmp_path):
    client, db, course = setup
    monkeypatch.setattr("app.core.config.settings.data_dir", tmp_path)
    book = make_book(client, course)
    png = PNG_1PX

    def upload():
        response = client.post(
            f"/api/v1/courses/{course.id}/notebooks/{book['id']}/attachments",
            files={"file": ("figure.png", png, "image/png")},
        )
        assert response.status_code == 201, response.text
        attachment = db.get(NotebookAttachment, response.json()["id"])
        db.execute(update(NotebookAttachment).where(
            NotebookAttachment.id == attachment.id,
        ).values(created_at=utc_now() - timedelta(days=2)))
        db.commit()
        return response.json()

    unused = upload()
    assert prune_unreferenced_attachments(db) == 1
    assert client.get(unused["url"]).status_code == 404

    used = upload()
    document = {"type": "doc", "content": [{"type": "image", "attrs": {
        "src": used["url"], "attachmentId": used["id"], "alt": "图",
    }}]}
    assert client.put(document_url(course, book), json={
        "schema_version": 2, "content": document, "expected_revision": 0,
    }).status_code == 200
    assert prune_unreferenced_attachments(db) == 0
    assert client.put(document_url(course, book), json={
        "schema_version": 2, "content": {"type": "doc", "content": []}, "expected_revision": 1,
    }).status_code == 200
    assert prune_unreferenced_attachments(db) == 0
    assert client.get(used["url"]).status_code == 200


def test_attachment_cleanup_removes_deleted_notebook_files(setup, monkeypatch, tmp_path):
    client, db, course = setup
    monkeypatch.setattr("app.core.config.settings.data_dir", tmp_path)
    book = make_book(client, course)
    png = PNG_1PX
    response = client.post(
        f"/api/v1/courses/{course.id}/notebooks/{book['id']}/attachments",
        files={"file": ("figure.png", png, "image/png")},
    )
    assert response.status_code == 201
    directory = tmp_path / "notebooks" / book["id"] / "images"
    image = next(directory.iterdir())
    stale = (utc_now() - timedelta(days=2)).timestamp()
    os.utime(image, (stale, stale))
    db.delete(db.get(Notebook, book["id"]))
    db.commit()
    assert prune_deleted_notebook_directories(db) == 1
    assert not directory.exists()


def test_attachment_cleanup_removes_interrupted_upload_file(setup, monkeypatch, tmp_path):
    client, db, course = setup
    monkeypatch.setattr("app.core.config.settings.data_dir", tmp_path)
    book = make_book(client, course)
    directory = tmp_path / "notebooks" / book["id"] / "images"
    directory.mkdir(parents=True)
    stray = directory / ("a" * 32 + ".png")
    stray.write_bytes(PNG_1PX)
    stale = (utc_now() - timedelta(days=2)).timestamp()
    os.utime(stray, (stale, stale))
    assert prune_stray_attachment_files(db) == 1
    assert not stray.exists()
