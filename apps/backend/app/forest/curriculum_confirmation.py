"""Atomic preview confirmation with revision guards and server-owned undo receipts."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.models import Course, CurriculumImport, ForestCourseProfile
from app.forest.curriculum_processing import job_snapshot, latest_job
from app.forest.errors import CurriculumOperationError
from app.forest.service import ensure_profile


def profile_values(profile):
    return {key: getattr(profile, key) for key in ('semester', 'level', 'prerequisites_json')}


def confirm_import(db, record, rows):
    try:
        _confirm(db, record, rows)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _confirm(db, record, rows):
    if record.status != 'preview':
        raise CurriculumOperationError(409, '只有预览完成的培养方案可以确认')
    originals = {row['key']: row for row in json.loads(record.rows_json)}
    keys, names, codes, course_ids = set(), set(), set(), set()
    for row in rows:
        original = originals.get(row.key)
        if row.key in keys or original is None or any(
            getattr(row, field) != original[field] for field in ('source_label', 'source_excerpt')
        ):
            raise CurriculumOperationError(422, '培养方案来源被修改或行标识无效，请重新读取预览')
        keys.add(row.key)
        if row.name.casefold() in names:
            raise CurriculumOperationError(422, '培养方案有重复课程名称，请合并或修正预览')
        names.add(row.name.casefold())
        if row.course_code:
            code = row.course_code.casefold()
            if code in codes:
                raise CurriculumOperationError(422, '培养方案有重复课程代码，请合并或修正预览')
            codes.add(code)
        if row.existing_course_id:
            if row.existing_course_id in course_ids:
                raise CurriculumOperationError(422, '同一课程只能关联一条培养方案课程记录')
            course_ids.add(row.existing_course_id)
            if row.expected_profile_revision is None:
                raise CurriculumOperationError(409, '关联课程的版本信息缺失，请重新读取预览并选择课程')
    # Acquire the write transaction before checking profiles/names; concurrent confirms cannot interleave.
    changed = db.execute(update(CurriculumImport).where(
        CurriculumImport.id == record.id, CurriculumImport.status == 'preview'
    ).values(status='confirmed', confirmed_at=datetime.now(UTC)))
    if changed.rowcount != 1:
        raise CurriculumOperationError(409, '培养方案已经被确认，请刷新')
    receipt, saved_rows = [], []
    for row in rows:
        created = row.existing_course_id is None
        if created:
            if db.scalar(select(Course.id).where(Course.name == row.name, Course.deleted_at.is_(None))):
                raise CurriculumOperationError(409, f'“{row.name}”已有同名课程，请选择关联课程')
            course = Course(name=row.name)
            db.add(course)
            db.flush()
        else:
            course = db.get(Course, row.existing_course_id, populate_existing=True)
            if course is None or course.deleted_at is not None:
                raise CurriculumOperationError(409, '所选关联课程已变化，请刷新')
        profile = ensure_profile(db, course)
        before = profile_values(profile)
        revision = profile.revision
        if not created and revision != row.expected_profile_revision:
            raise CurriculumOperationError(409, f'“{course.name}”已在其他页面修改，请刷新课程并重新关联')
        values = {'semester': row.semester, 'level': row.level,
                  'prerequisites_json': json.dumps(row.prerequisites, ensure_ascii=False)}
        changed = db.execute(update(ForestCourseProfile).where(
            ForestCourseProfile.course_id == course.id, ForestCourseProfile.revision == revision
        ).values(**values, revision=revision + 1))
        if changed.rowcount != 1:
            raise CurriculumOperationError(409, f'“{course.name}”版本已变化，请刷新')
        receipt.append({'course_id': course.id, 'name': course.name, 'description': course.description,
                        'created': created, 'before': before, 'after': values, 'after_revision': revision + 1})
        saved_rows.append(row.model_copy(update={
            'existing_course_id': course.id, 'expected_profile_revision': revision + 1}).model_dump())
    job = latest_job(db, record)
    if job:
        snapshot = job_snapshot(job)
        snapshot['confirmation'] = {'version': 1, 'courses': receipt}
        job.source_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    record.rows_json = json.dumps(saved_rows, ensure_ascii=False)
