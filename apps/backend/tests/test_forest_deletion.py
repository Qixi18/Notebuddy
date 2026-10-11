"""Deletion must not invalidate a durable forest job while it is reading notes."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Course, ForestJob, Material
from app.services.deletion import DeletionConflict, impact_preview, soft_delete_course


@pytest.fixture
def workspace():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course, other = Course(name="离散数学"), Course(name="数字逻辑")
        db.add_all([course, other])
        db.flush()
        material = Material(course_id=other.id, lecture_title="布尔代数",
                            original_filename="logic.pdf", stored_filename="logic.pdf",
                            size_bytes=1)
        db.add(material)
        db.commit()
        yield db, course, other, material
    engine.dispose()


def test_pending_source_course_relation_job_blocks_course_deletion(workspace, monkeypatch):
    db, course, _, _ = workspace
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    db.add(ForestJob(kind="cross_course_relations", course_id=course.id, status="pending"))
    db.commit()
    assert impact_preview(db, course_id=course.id)["active_jobs"] == 1
    with pytest.raises(DeletionConflict):
        soft_delete_course(db, course)
    assert course.deleted_at is None


def test_running_cross_course_job_blocks_target_material_deletion(workspace):
    db, course, other, material = workspace
    db.add(ForestJob(kind="cross_course_relations", course_id=course.id, status="processing"))
    db.commit()
    assert impact_preview(db, course_id=other.id, material_id=material.id)["active_jobs"] == 1


def test_finished_forest_job_does_not_block_course_deletion(workspace, monkeypatch):
    db, course, _, _ = workspace
    monkeypatch.setattr("app.services.deletion._checkpoint", lambda: None)
    db.add(ForestJob(kind="cross_course_relations", course_id=course.id, status="failed"))
    db.commit()
    soft_delete_course(db, course)
    assert course.deleted_at is not None
