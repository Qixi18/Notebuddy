"""Undo is tested only against synthetic in-memory courses."""
from __future__ import annotations

import json

import pytest

from app.db.models import Course, ForestCourseProfile
from app.forest import curriculum_revert
from app.forest.curriculum import confirm_import
from app.forest.errors import CurriculumOperationError
from tests.notebook_fixtures import make_notebook
from tests.test_curriculum_import import preview

pytest_plugins = ['tests.notebook_fixtures']


@pytest.fixture
def checkpoints(monkeypatch):
    calls = []
    monkeypatch.setattr(curriculum_revert, 'checkpoint_before_revert', lambda: calls.append(True))
    return calls


def test_revert_restores_existing_profile_and_recycles_only_empty_new_course(session, checkpoints):
    course = Course(name='高等数学')
    session.add(course)
    session.flush()
    profile = ForestCourseProfile(course_id=course.id, semester=8, level='application', revision=2,
                                  prerequisites_json='["原有先修"]')
    session.add(profile)
    session.commit()
    record, rows = preview(session, '课程名称 | 学期\n高等数学 | 1\n英语 | 2')
    confirm_import(session, record, rows)
    new_id = json.loads(record.rows_json)[1]['existing_course_id']
    impact = curriculum_revert.revert_preview(session, record)
    assert [item['name'] for item in impact['recycle_courses']] == ['英语']
    assert [item['name'] for item in impact['restore_courses']] == ['高等数学']
    curriculum_revert.revert_import(session, record)
    session.refresh(profile)
    assert (profile.semester, profile.level, profile.revision) == (8, 'application', 4)
    assert profile.prerequisites_json == '["原有先修"]'
    assert session.get(Course, new_id).deleted_at is not None
    assert course.deleted_at is None
    assert record.status == 'reverted'
    assert checkpoints == [True]
    with pytest.raises(CurriculumOperationError):
        curriculum_revert.revert_import(session, record)
    assert checkpoints == [True]


@pytest.mark.parametrize('change', ['profile', 'rename', 'description', 'notebook'])
def test_revert_refuses_any_later_use_without_partial_changes(session, checkpoints, change):
    record, rows = preview(session, '课程名称 | 学期\n数学 | 1\n英语 | 2')
    confirm_import(session, record, rows)
    ids = [row['existing_course_id'] for row in json.loads(record.rows_json)]
    course = session.get(Course, ids[1])
    if change == 'profile':
        session.get(ForestCourseProfile, course.id).revision += 1
    elif change == 'rename':
        course.name = '用户改名'
    elif change == 'description':
        course.description = '用户内容'
    else:
        make_notebook(session, course)
    session.commit()
    with pytest.raises(CurriculumOperationError) as caught:
        curriculum_revert.revert_import(session, record)
    assert caught.value.status_code == 409
    assert all(session.get(Course, course_id).deleted_at is None for course_id in ids)
    assert record.status == 'confirmed'
    assert checkpoints == []


def test_legacy_confirmed_import_has_no_fabricated_undo_receipt(session, checkpoints):
    from app.db.models import CurriculumImport
    record = CurriculumImport(status='confirmed')
    session.add(record)
    session.commit()
    with pytest.raises(CurriculumOperationError) as caught:
        curriculum_revert.revert_import(session, record)
    assert caught.value.status_code == 409
    assert checkpoints == []


def test_checkpoint_failure_keeps_entire_plan_confirmed(session, monkeypatch):
    record, rows = preview(session)
    confirm_import(session, record, rows)
    def fail():
        raise OSError('synthetic disk error')
    monkeypatch.setattr(curriculum_revert, 'checkpoint_before_revert', fail)
    with pytest.raises(CurriculumOperationError) as caught:
        curriculum_revert.revert_import(session, record)
    assert caught.value.status_code == 503
    assert record.status == 'confirmed'
    assert session.get(Course, json.loads(record.rows_json)[0]['existing_course_id']).deleted_at is None


def test_changes_during_backup_are_revalidated_before_any_recycle(session, monkeypatch):
    record, rows = preview(session)
    confirm_import(session, record, rows)
    course_id = json.loads(record.rows_json)[0]['existing_course_id']
    def changed_during_backup():
        session.get(Course, course_id).description = '后续内容'
        session.commit()
    monkeypatch.setattr(curriculum_revert, 'checkpoint_before_revert', changed_during_backup)
    with pytest.raises(CurriculumOperationError):
        curriculum_revert.revert_import(session, record)
    assert record.status == 'confirmed'
    assert session.get(Course, course_id).deleted_at is None
