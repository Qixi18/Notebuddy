"""Full backend chain: upload -> parse -> IR -> generate -> document -> search/agent."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base, get_db
from app.db.models import (
    Material,
    NotebookGenerationJob,
    ProcessingJob,
)
from app.main import app
from app.workers import material_worker, notebook_generation_worker

pymupdf = pytest.importorskip("pymupdf")

pytest_plugins = ["tests.notebook_fixtures"]


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(material_worker, "SessionLocal", factory)
    monkeypatch.setattr(notebook_generation_worker, "SessionLocal", factory)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield engine, factory, tmp_path
    app.dependency_overrides.pop(get_db, None)
    monkeypatch.undo()
    engine.dispose()


def _pdf(tmp_path: Path) -> bytes:
    path = tmp_path / "limits.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Chapter 1 Limits", fontsize=22)
    page.insert_text((72, 130), "The limit of f(x) as x approaches a is L.", fontsize=11)
    page.insert_text((72, 150), "Limits are the foundation of calculus and analysis.", fontsize=11)
    page.insert_text((72, 170), "A function may fail to have a limit at a point.", fontsize=11)
    page.insert_text((72, 190), "Left and right limits must agree for the limit to exist.",
                     fontsize=11)
    document.save(str(path))
    document.close()
    return path.read_bytes()


def _create_course_and_book(client: TestClient) -> tuple[str, str]:
    course = client.post("/api/v1/courses", json={"name": "数学分析"}).json()
    book = client.post(f"/api/v1/courses/{course['id']}/notebooks",
                       json={"title": "极限笔记"}).json()
    return course["id"], book["id"]


def _upload(client: TestClient, notebook_id: str, content: bytes, name: str = "limits.pdf"):
    response = client.post(
        f"/api/v1/notebooks/{notebook_id}/assets",
        files={"file": (name, content, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_until_generation(engine) -> None:
    from app.services.notebook_generation_inputs import coordinate_generation_inputs

    with Session(engine) as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.status == "pending"))
        assert job is not None
        job.status = "processing"
        job_id = job.id
        db.commit()
    material_worker.process_material(job_id)
    with Session(engine) as db:
        coordinate_generation_inputs(db)
        db.commit()
        generation = db.scalar(select(NotebookGenerationJob))
        assert generation is not None, "generation job was not enqueued"
        generation_id = generation.id
    claimed = notebook_generation_worker.claim_next_generation_job()
    assert claimed == generation_id
    notebook_generation_worker.process_generation_job(claimed)


def test_upload_parse_generate_edit_restore_search_and_agent(env):
    engine, _factory, tmp_path = env
    with TestClient(app) as client:
        course_id, notebook_id = _create_course_and_book(client)
        uploaded = _upload(client, notebook_id, _pdf(tmp_path))
        assert uploaded["asset"]["id"]

        _run_until_generation(engine)

        # Material course ownership stays empty; Notebook is the authority.
        with Session(engine) as db:
            material = db.scalar(select(Material))
            assert material.course_id is None
            assert material.notebook_id == notebook_id
            run = db.scalar(select(NotebookGenerationJob))
            assert run.status == "completed", run.error_message

        document = client.get(f"/api/v1/courses/{course_id}/notebooks/{notebook_id}/document")
        assert document.status_code == 200
        body = document.json()
        assert body["revision"] >= 1
        text = str(body["content"])
        assert "Chapter 1 Limits" in text
        assert "limit" in text.lower()

        # Editor save + history restore.
        content = body["content"]
        content["content"].append({
            "type": "paragraph", "attrs": {"blockId": "user-edit-1"},
            "content": [{"type": "text", "text": "用户补充：极限与连续的关系"}],
        })
        saved = client.put(
            f"/api/v1/courses/{course_id}/notebooks/{notebook_id}/document",
            json={"schema_version": 2, "content": content,
                  "expected_revision": body["revision"]},
        )
        assert saved.status_code == 200, saved.text
        edited_revision = saved.json()["revision"]
        restored = client.post(
            f"/api/v1/courses/{course_id}/notebooks/{notebook_id}/revisions/{body['revision']}/restore",
            json={"expected_revision": edited_revision},
        )
        assert restored.status_code == 200, restored.text
        assert "用户补充" not in str(restored.json()["content"])

        # Course overview / knowledge structure use Notebook body.
        overview = client.get(f"/api/v1/courses/{course_id}/overview")
        assert overview.status_code == 200
        assert overview.json()["counts"]["notebooks"] == 1
        assert overview.json()["counts"]["sections"] >= 1
        structure = client.get(f"/api/v1/courses/{course_id}/knowledge-structure").json()
        assert structure["notebooks"][0]["sections"]

        # Knowledge forest search finds body text.
        search = client.get("/api/v1/forest/search", params={"q": "Chapter"})
        assert search.status_code == 200
        assert any(item["notebook_id"] == notebook_id for item in search.json())

        # Two-path retrieval + agent tools.
        from app.ai.agent_tools import execute_tool
        from app.retrieval.service import retrieve

        with Session(engine) as db:
            chunks = retrieve(db, course_id=course_id, question="limit calculus", limit=6)
            kinds = {chunk.kind for chunk in chunks}
            assert "document" in kinds
            outcome = execute_tool(
                db, course_id=course_id, name="search_course",
                arguments={"query": "limit calculus"}, scope="course",
            )
            assert outcome.chunks
            read = execute_tool(
                db, course_id=course_id, name="read_notebook",
                arguments={"notebook_id": notebook_id}, scope="course",
                locked_notebook_id=notebook_id,
            )
            assert "Chapter 1 Limits" in read.payload_text


def test_unbound_notebook_can_upload_parse_and_generate(env):
    engine, _factory, tmp_path = env
    with TestClient(app) as client:
        created = client.post("/api/v1/notebooks/unbound", json={"title": "未分类笔记"})
        assert created.status_code == 201, created.text
        notebook_id = created.json()["id"]
        _upload(client, notebook_id, _pdf(tmp_path))

        _run_until_generation(engine)

        document = client.get(f"/api/v1/notebooks/unbound/{notebook_id}/document")
        assert document.status_code == 200
        assert "Chapter 1 Limits" in str(document.json()["content"])

        course = client.post("/api/v1/courses", json={"name": "数学分析"}).json()
        bound = client.post(f"/api/v1/notebooks/{notebook_id}/bind",
                            json={"course_id": course["id"]})
        assert bound.status_code == 200, bound.text
        overview = client.get(f"/api/v1/courses/{course['id']}/overview").json()
        assert overview["counts"]["notebooks"] == 1
        assert overview["counts"]["sections"] >= 1


def test_notebook_asset_can_be_restored_only_by_its_owner_notebook(env):
    _engine, _factory, tmp_path = env
    with TestClient(app) as client:
        _course_id, notebook_id = _create_course_and_book(client)
        uploaded = _upload(client, notebook_id, _pdf(tmp_path))
        asset_id = uploaded["asset"]["id"]

        removed = client.delete(f"/api/v1/notebooks/{notebook_id}/assets/{asset_id}")
        assert removed.status_code == 200, removed.text
        detached = client.get(f"/api/v1/notebooks/{notebook_id}/detached-assets")
        assert detached.status_code == 200, detached.text
        assert [row["id"] for row in detached.json()] == [asset_id]

        other_course = client.post("/api/v1/courses", json={"name": "另一门课"}).json()
        other_book = client.post(
            f"/api/v1/courses/{other_course['id']}/notebooks", json={"title": "另一笔记"},
        ).json()
        unauthorized = client.post(
            f"/api/v1/notebooks/{other_book['id']}/assets/{asset_id}/restore",
        )
        assert unauthorized.status_code == 404

        restored = client.post(
            f"/api/v1/notebooks/{notebook_id}/assets/{asset_id}/restore",
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["id"] == asset_id
        assert [row["id"] for row in client.get(
            f"/api/v1/notebooks/{notebook_id}/assets",
        ).json()] == [asset_id]
        assert client.get(f"/api/v1/notebooks/{notebook_id}/detached-assets").json() == []
