"""Protected, checkpointed undo; never deletes later user content."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update

from app.core.config import settings
from app.db.checkpoint import create_checkpoint
from app.db.database import Base
from app.db.models import Course, CurriculumImport, ForestCourseProfile
from app.forest.curriculum_confirmation import profile_values
from app.forest.curriculum_processing import job_snapshot, latest_job


def checkpoint_before_revert():
    suffix = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    create_checkpoint(settings.data_dir, settings.backups_dir / f'pre-curriculum-revert-{suffix}')


def _receipt(db, record):
    confirmation = job_snapshot(latest_job(db, record)).get('confirmation', {})
    if record.status != 'confirmed' or confirmation.get('version') != 1 or not confirmation.get('courses'):
        raise HTTPException(409, '该记录未确认、已撤销或没有可验证的撤销快照')
    return confirmation


def _used(db, course):
    if course.notebook_order_revision or course.last_opened_at:
        return True
    # Include all current and compatibility references, even items in the recycle bin.
    for table in Base.metadata.sorted_tables:
        if table.name == ForestCourseProfile.__tablename__:
            continue
        for column in table.columns:
            if (any(key.column.table.name == 'courses' for key in column.foreign_keys)
                    and db.execute(select(column).where(column == course.id).limit(1)).first()):
                return True
    return False


def _impact(db, receipt):
    restore, recycle = [], []
    for item in receipt['courses']:
        course = db.get(Course, item['course_id'], populate_existing=True)
        profile = db.get(ForestCourseProfile, item['course_id'], populate_existing=True)
        if (course is None or course.deleted_at is not None or profile is None
                or profile.revision != item['after_revision'] or profile_values(profile) != item['after']):
            raise HTTPException(409, f'“{item["name"]}”已在确认后修改，无法安全撤销整个方案')
        if item['created']:
            if course.name != item['name'] or course.description != item['description'] or _used(db, course):
                raise HTTPException(409, f'“{item["name"]}”已被使用或修改，无法安全撤销整个方案')
            recycle.append({'course_id': course.id, 'name': course.name})
        else:
            restore.append({'course_id': course.id, 'name': course.name,
                            'semester': item['before']['semester'], 'level': item['before']['level'],
                            'prerequisites': json.loads(item['before']['prerequisites_json'])})
    return {'restore_courses': restore, 'recycle_courses': recycle}


def revert_preview(db, record):
    return _impact(db, _receipt(db, record))


def revert_import(db, record):
    import_id = record.id
    try:
        receipt = _receipt(db, record)
        _impact(db, receipt)
        # Backup uses its own online connection. Release the read transaction first.
        db.rollback()
        try:
            checkpoint_before_revert()
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(503, '撤销前检查点创建失败，未修改课程，请检查备份目录后重试') from exc
        changed = db.execute(update(CurriculumImport).where(
            CurriculumImport.id == import_id, CurriculumImport.status == 'confirmed'
        ).values(status='reverted'))
        if changed.rowcount != 1:
            raise HTTPException(409, '培养方案状态已变化，请刷新')
        # The write transaction now excludes concurrent SQLite writers; recheck after the backup.
        _impact(db, receipt)
        for item in receipt['courses']:
            changed = db.execute(update(ForestCourseProfile).where(
                ForestCourseProfile.course_id == item['course_id'],
                ForestCourseProfile.revision == item['after_revision']
            ).values(**item['before'], revision=item['after_revision'] + 1))
            if changed.rowcount != 1:
                raise HTTPException(409, '课程版本已变化，未撤销任何课程')
            if item['created']:
                db.execute(update(Course).where(Course.id == item['course_id']).values(deleted_at=datetime.now(UTC)))
        db.commit()
    except Exception:
        db.rollback()
        raise
