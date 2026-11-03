from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import (
    AssetProcessingJob,
    Notebook,
    NotebookAsset,
    NotebookGenerationJob,
    ProcessingJob,
)
from app.main import app
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


def test_course_notebook_rename_requires_active_course(session):
    course = make_course(session, "有效课程")
    book = make_notebook(session, course, "原名")
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        ok = client.patch(
            f"/api/v1/courses/{course.id}/notebooks/{book.id}", json={"title": "新名"},
        )
        assert ok.status_code == 200
        course.deleted_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
        session.commit()
        deleted = client.patch(
            f"/api/v1/courses/{course.id}/notebooks/{book.id}", json={"title": "不应修改"},
        )
        missing = client.patch(
            "/api/v1/courses/not-a-course/notebooks/not-a-book", json={"title": "无效"},
        )
        assert deleted.status_code == 404
        assert missing.status_code == 404
        session.refresh(book)
        assert book.title == "新名"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_default_notebook_selects_stable_replacement(session):
    from app.services.notebook_lifecycle import delete_course_notebook

    course = make_course(session, "课程")
    first = make_notebook(session, course, "默认")
    second = Notebook(course_id=course.id, title="第二", tree_slot=1, display_order=2, is_default=False)
    third = Notebook(course_id=course.id, title="第三", tree_slot=2, display_order=1, is_default=False)
    session.add_all([second, third])
    session.commit()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.services.notebook_lifecycle._checkpoint", lambda: None)
        monkeypatch.setattr("app.services.notebook_lifecycle._active_course", lambda _db, _id: course)
        delete_course_notebook(session, course.id, first.id)
    session.refresh(second)
    session.refresh(third)
    assert third.is_default is True
    assert second.is_default is False


def test_delete_non_default_keeps_existing_default(session):
    from app.services.notebook_lifecycle import delete_course_notebook

    course = make_course(session, "课程")
    default = make_notebook(session, course, "默认")
    session.flush()
    default.is_default = True
    session.flush()
    other = Notebook(course_id=course.id, title="其他", tree_slot=1, display_order=1, is_default=False)
    session.add(other)
    session.commit()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.services.notebook_lifecycle._checkpoint", lambda: None)
        delete_course_notebook(session, course.id, other.id)
    session.refresh(default)
    assert default.is_default is True


def test_deleted_course_rejects_notebook_delete_without_side_effect(session):
    from datetime import UTC, datetime

    course = make_course(session, "已删除课程")
    book = make_notebook(session, course, "笔记")
    course.deleted_at = datetime.now(UTC)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).delete(
            f"/api/v1/courses/{course.id}/notebooks/{book.id}"
        )
        assert response.status_code == 404
        session.refresh(book)
        assert book.deleted_at is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_unbound_notebook_lifecycle_remains_available(session):
    from app.services.notebook_lifecycle import create_unbound_notebook, rename_notebook

    book = create_unbound_notebook(session, "未绑定")
    updated = rename_notebook(session, book.id, "仍未绑定")
    assert updated.course_id is None
    assert updated.title == "仍未绑定"


@pytest.mark.parametrize(
    ("job_kind", "status"),
    [
        (kind, status)
        for kind in ("material", "image", "generation")
        for status in ("pending", "processing", "cancel_requested")
    ],
)
def test_each_active_job_kind_blocks_course_notebook_delete(session, monkeypatch, job_kind, status):
    from app.services.errors import ApplicationError
    from app.services.notebook_lifecycle import delete_course_notebook
    from tests.notebook_fixtures import make_asset, make_course, make_material

    course = make_course(session, "课程")
    book = make_notebook(session, course, "默认笔记")
    asset = make_asset(
        session, book,
        media_type="image" if job_kind == "image" else "document",
        extension=".png" if job_kind == "image" else ".pdf",
    )
    material = make_material(session, book, asset)
    session.flush()

    if job_kind == "material":
        job = ProcessingJob(material_id=material.id, kind="parse_material", status=status)
    elif job_kind == "image":
        owner = session.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset.id,
            NotebookAsset.is_owner.is_(True),
        ))
        job = AssetProcessingJob(
            asset_id=asset.id, notebook_id=book.id, owner_link_id=owner.id,
            kind="image_parse", status=status,
        )
    else:
        job = NotebookGenerationJob(
            notebook_id=book.id, idempotency_key=f"active-{status}",
            request_fingerprint="f" * 64, status=status, base_document_revision=0,
            input_snapshot_json="{}", model="test", prompt_version="test",
        )
    session.add(job)
    session.commit()
    monkeypatch.setattr("app.services.notebook_lifecycle._checkpoint", lambda: None)

    with pytest.raises(ApplicationError) as error:
        delete_course_notebook(session, course.id, book.id)

    assert error.value.status_code == 409
    session.refresh(book)
    assert book.deleted_at is None
    assert book.is_default is True


def test_bulk_delete_is_atomic_when_one_notebook_has_an_active_job(session, monkeypatch):
    from app.services.errors import ApplicationError
    from app.services.notebook_lifecycle import bulk_manage_notebooks
    from tests.notebook_fixtures import make_asset, make_course, make_material

    course = make_course(session, "课程")
    first = make_notebook(session, course, "默认笔记")
    second = Notebook(
        course_id=course.id, title="第二本", tree_slot=1, display_order=1,
        is_default=False,
    )
    session.add(second)
    session.flush()
    asset = make_asset(session, second)
    material = make_material(session, second, asset)
    session.add(ProcessingJob(material_id=material.id, kind="parse_material", status="processing"))
    session.commit()
    monkeypatch.setattr("app.services.notebook_lifecycle._checkpoint", lambda: None)

    with pytest.raises(ApplicationError):
        bulk_manage_notebooks(
            session, [first.id, second.id], action="delete", course_id=None,
        )

    session.refresh(first)
    session.refresh(second)
    assert first.deleted_at is None and second.deleted_at is None
    assert first.is_default is True and second.is_default is False


def test_bulk_delete_promotes_first_remaining_notebook_deterministically(session, monkeypatch):
    from app.services.notebook_lifecycle import bulk_manage_notebooks
    from tests.notebook_fixtures import make_course

    course = make_course(session, "课程")
    first = make_notebook(session, course, "默认笔记")
    second = Notebook(
        course_id=course.id, title="第二本", tree_slot=1, display_order=3,
        is_default=False,
    )
    third = Notebook(
        course_id=course.id, title="第三本", tree_slot=2, display_order=1,
        is_default=False,
    )
    session.add_all([second, third])
    session.commit()
    monkeypatch.setattr("app.services.notebook_lifecycle._checkpoint", lambda: None)

    result = bulk_manage_notebooks(
        session, [first.id, second.id], action="delete", course_id=None,
    )

    assert result["affected"] == 2
    session.refresh(third)
    assert third.is_default is True


def test_moving_or_unbinding_default_promotes_source_replacement(session, monkeypatch):
    from app.services.notebook_lifecycle import move_notebook
    from tests.notebook_fixtures import make_course

    source = make_course(session, "来源课程")
    target = make_course(session, "目标课程")
    moving = make_notebook(session, source, "待移动")
    replacement = Notebook(
        course_id=source.id, title="留在来源课程", tree_slot=1,
        display_order=2, is_default=False,
    )
    session.add(replacement)
    session.commit()
    monkeypatch.setattr("app.forest.notebook_relations.enqueue_notebook_relations", lambda *_a, **_k: None)

    move_notebook(session, moving.id, target.id)
    session.refresh(replacement)
    assert replacement.is_default is True


@pytest.mark.parametrize("job_kind", ["material", "image", "generation"])
def test_permanent_notebook_delete_rejects_cancel_requested_jobs_before_cleanup(
    session, monkeypatch, job_kind,
):
    from datetime import UTC, datetime

    from app.services.deletion import DeletionConflict, permanently_delete_notebook
    from tests.notebook_fixtures import make_asset, make_material

    course = make_course(session, "回收站课程")
    book = make_notebook(session, course, "回收站笔记")
    book.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    asset = make_asset(
        session, book,
        media_type="image" if job_kind == "image" else "document",
        extension=".png" if job_kind == "image" else ".pdf",
    )
    material = make_material(session, book, asset)
    session.flush()

    if job_kind == "material":
        job = ProcessingJob(material_id=material.id, kind="parse_material", status="cancel_requested")
    elif job_kind == "image":
        owner = session.scalar(select(NotebookAsset).where(
            NotebookAsset.asset_id == asset.id,
            NotebookAsset.is_owner.is_(True),
        ))
        job = AssetProcessingJob(
            asset_id=asset.id, notebook_id=book.id, owner_link_id=owner.id,
            kind="image_parse", status="cancel_requested",
        )
    else:
        job = NotebookGenerationJob(
            notebook_id=book.id, idempotency_key="cancel-purge",
            request_fingerprint="f" * 64, status="cancel_requested",
            base_document_revision=0, input_snapshot_json="{}", model="test",
            prompt_version="test",
        )
    session.add(job)
    session.commit()
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: pytest.fail("checkpoint must not run"))

    with pytest.raises(DeletionConflict):
        permanently_delete_notebook(session, book)

    assert session.get(Notebook, book.id) is not None
    assert session.get(type(job), job.id) is not None
