"""后台任务工作者的行为测试。

锁定的核心约束（正是「一直在解析」故障的根因）：

1. 上传接口**不再在请求进程内执行解析**——只写一条 pending 任务就返回。
   早期用 `BackgroundTasks` 时，后端一重启任务就永久丢失，状态卡在
   `processing`，界面上永远显示「解析中」。
2. 进程启动时，上次遗留的 `processing` 任务必须被**自动放回 pending**
   （自愈），否则它们会永远卡住。
3. claim 是条件更新，同一任务不会被重复取走。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Course, Material, ProcessingJob
from app.workers.job_worker import JobWorker


@pytest.fixture()
def session_factory(monkeypatch: pytest.MonkeyPatch):
    """把 worker 的 SessionLocal 换到独立的内存库上。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    def _make() -> Session:
        return Session(engine)

    monkeypatch.setattr("app.workers.job_worker.SessionLocal", _make)
    return _make


def _material(db: Session) -> str:
    """建一套 课程+材料+pending任务，返回**材料 id**（不是实例）。

    返回标量而非 ORM 实例，是因为 commit 之后实例属性即失效，
    session 关闭后再访问就会抛 DetachedInstanceError。
    """
    course = Course(name="线性代数")
    db.add(course)
    db.flush()
    material = Material(
        course_id=course.id,
        lecture_title="第一讲",
        original_filename="a.pptx",
        stored_filename="s.pptx",
        size_bytes=1,
    )
    db.add(material)
    db.flush()
    db.commit()
    return material.id


def _add_job(db: Session, material_id: str, status: str, progress: int = 0) -> str:
    """追加一条任务，返回其 **id**（理由同 `_material`）。"""
    job = ProcessingJob(
        material_id=material_id, kind="parse_material", status=status, progress=progress
    )
    db.add(job)
    db.commit()
    return job.id


# ---------- 启动自愈 ----------


def test_recover_resets_stuck_processing_jobs(session_factory) -> None:
    """回归「一直在解析」：遗留的 processing 任务必须被放回 pending。"""
    db = session_factory()
    material_id = _material(db)
    stuck_id = _add_job(db, material_id, "processing", progress=95)
    db.close()

    recovered = JobWorker()._recover_stuck_jobs()

    assert recovered == 1
    db = session_factory()
    refreshed = db.get(ProcessingJob, stuck_id)
    assert refreshed.status == "pending"
    assert refreshed.progress == 0
    assert refreshed.error_message is None
    db.close()


def test_recover_leaves_completed_jobs_alone(session_factory) -> None:
    """已完成的任务不应被自愈逻辑重新排队。"""
    db = session_factory()
    material_id = _material(db)
    _add_job(db, material_id, "pending")
    done_id = _add_job(db, material_id, "completed", progress=100)
    db.close()

    recovered = JobWorker()._recover_stuck_jobs()

    assert recovered == 0
    db = session_factory()
    assert db.get(ProcessingJob, done_id).status == "completed"
    db.close()


def test_recover_clears_previous_error_message(session_factory) -> None:
    """重跑前必须清掉上次的报错，否则界面会一直显示幽灵错误。"""
    db = session_factory()
    material_id = _material(db)
    job_id = _add_job(db, material_id, "processing", progress=50)
    # 通过 UPDATE 写 error_message，避免依赖已过期的实例
    db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(error_message="上次失败的原因")
    )
    db.commit()
    db.close()

    JobWorker()._recover_stuck_jobs()

    db = session_factory()
    assert db.get(ProcessingJob, job_id).error_message is None
    db.close()


# ---------- claim ----------


def test_claim_takes_pending_job_and_marks_processing(session_factory) -> None:
    db = session_factory()
    _add_job(db, _material(db), "pending")
    pending_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.status == "pending"))
    db.close()

    claimed = JobWorker()._claim_next_job()

    assert claimed == pending_id
    db = session_factory()
    assert db.get(ProcessingJob, pending_id).status == "processing"
    db.close()


def test_claim_returns_none_when_queue_empty(session_factory) -> None:
    db = session_factory()
    _add_job(db, _material(db), "pending")
    # 把唯一的任务置为已完成，队列应为空
    db.execute(update(ProcessingJob).values(status="completed"))
    db.commit()
    db.close()

    assert JobWorker()._claim_next_job() is None


def test_claim_does_not_take_processing_job(session_factory) -> None:
    """正在处理中的任务不能被再次取走（否则会重复执行）。"""
    db = session_factory()
    _add_job(db, _material(db), "pending")
    db.execute(update(ProcessingJob).values(status="processing"))
    db.commit()
    db.close()

    assert JobWorker()._claim_next_job() is None


def test_claim_is_fifo_by_creation_time(session_factory) -> None:
    """按创建时间先到先服务，避免后上传的任务插队。"""
    db = session_factory()
    material_id = _material(db)
    _add_job(db, material_id, "pending")
    first_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.status == "pending"))
    # 再压一条更晚的任务，claim 必须仍取第一条
    _add_job(db, _material(db), "pending")
    db.close()

    claimed = JobWorker()._claim_next_job()

    assert claimed == first_id


# ---------- 不变量 ----------


def test_claim_marks_exactly_one_job(session_factory) -> None:
    """一次 claim 只应认领一个任务，且状态唯一。"""
    db = session_factory()
    material_id = _material(db)
    _add_job(db, material_id, "pending")
    _add_job(db, _material(db), "pending")
    db.close()

    JobWorker()._claim_next_job()

    db = session_factory()
    assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 2
    assert (
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status == "processing")
        )
        == 1
    )
    db.close()
