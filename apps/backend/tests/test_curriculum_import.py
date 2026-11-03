"""Curriculum jobs and previews use isolated synthetic data only."""
from __future__ import annotations

import json

import pytest

from app.db.models import Course, CurriculumImport, ForestCourseProfile, ForestJob
from app.forest.curriculum import confirm_import, create_import, extract_curriculum
from app.forest.errors import CurriculumOperationError
from app.schemas.forest_imports import CurriculumRow
from app.services.errors import ApplicationError
from app.services.forest_imports import get_curriculum_import, retry_curriculum_import

pytest_plugins = ["tests.notebook_fixtures"]


def failed_import(session):
    record = CurriculumImport(status="failed", input_text="Synthetic course table",
                              error_message="Synthetic failure")
    session.add(record)
    session.flush()
    job = ForestJob(kind="curriculum_import", curriculum_import_id=record.id,
                    status="failed", progress=45, error_message="Synthetic failure")
    session.add(job)
    session.commit()
    return record, job


def test_retry_returns_pending_and_preserves_completed_progress(session):
    record, job = failed_import(session)
    response = retry_curriculum_import(session, record.id)
    assert response["status"] == "pending"
    assert response["error_message"] is None
    assert response["progress"] == 45
    assert job.status == "pending"
    assert job.error_message is None


def test_repeated_retry_is_rejected_without_restarting_the_queued_job(session):
    record, job = failed_import(session)
    retry_curriculum_import(session, record.id)
    with pytest.raises(ApplicationError) as caught:
        retry_curriculum_import(session, record.id)
    assert caught.value.status_code == 409
    assert job.status == "pending"


def test_confirmed_record_cannot_be_requeued_by_a_stale_failed_job(session):
    record, job = failed_import(session)
    record.status = "confirmed"
    session.commit()
    with pytest.raises(ApplicationError) as caught:
        retry_curriculum_import(session, record.id)
    assert caught.value.status_code == 409
    assert get_curriculum_import(session, record.id)["status"] == "confirmed"
    assert job.status == "failed"


def preview(session, text="课程名称 | 学期\n高等数学 | 1"):
    record = create_import(session, text=text, processing_route="standard")
    extract_curriculum(session, record)
    session.commit()
    return record, [CurriculumRow.model_validate(row) for row in json.loads(record.rows_json)]


def test_local_metadata_is_extracted_and_confirmed_mapping_is_retained(session):
    record, rows = preview(session, "课程代码 | 课程名称 | 学分 | 学时 | 性质 | 学期\nM101 | 高等数学 | 4.5 | 72 | 必修 | 1")
    row = rows[0]
    assert (row.course_code, row.credits, row.hours, row.requirement) == ("M101", 4.5, 72, "required")
    confirm_import(session, record, rows)
    saved = json.loads(record.rows_json)[0]
    assert saved["existing_course_id"] is not None
    assert saved["credits"] == 4.5
    assert session.get(Course, saved["existing_course_id"]).name == "高等数学"
    snapshot = json.loads(session.get(
        ForestJob, get_curriculum_import(session, record.id)["job_id"],
    ).source_snapshot_json)
    assert snapshot["confirmation"]["courses"][0]["created"] is True


def test_confirmation_refuses_stale_profile_and_writes_nothing(session):
    course = Course(name="高等数学")
    session.add(course)
    session.flush()
    profile = ForestCourseProfile(course_id=course.id, revision=3, semester=2)
    session.add(profile)
    session.commit()
    record, rows = preview(session)
    assert rows[0].expected_profile_revision == 3
    profile.revision = 4
    profile.semester = 5
    session.commit()
    with pytest.raises(CurriculumOperationError) as caught:
        confirm_import(session, record, rows)
    assert caught.value.status_code == 409
    assert profile.semester == 5
    assert record.status == "preview"


def test_confirmation_rejects_duplicate_course_codes(session):
    record, rows = preview(session, "课程名称 | 学期\n数学 | 1\n英语 | 1")
    rows = [row.model_copy(update={"course_code": "A01"}) for row in rows]
    with pytest.raises(CurriculumOperationError) as caught:
        confirm_import(session, record, rows)
    assert caught.value.status_code == 422


def test_late_confirmation_conflict_rolls_back_earlier_new_course(session):
    from sqlalchemy import select
    course = Course(name='已有课程')
    session.add(course)
    session.flush()
    session.add(ForestCourseProfile(course_id=course.id, revision=1))
    session.commit()
    record, rows = preview(session, '课程名称 | 学期\n新课程 | 1\n已有课程 | 2')
    session.get(ForestCourseProfile, course.id).revision += 1
    session.commit()
    with pytest.raises(CurriculumOperationError):
        confirm_import(session, record, rows)
    assert session.scalar(select(Course).where(Course.name == '新课程')) is None
    assert record.status == 'preview'
