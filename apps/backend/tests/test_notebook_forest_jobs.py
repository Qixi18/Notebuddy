"""Automatic cross-course links use Notebook body versions, never legacy Notes."""

import json

import pytest
from sqlalchemy import select

from app.db.models import ForestJob, NotebookRelation
from app.forest import jobs, notebook_relations
from app.forest.notebook_relations import enqueue_notebook_relations
from app.notes.store import write_document
from tests.notebook_fixtures import make_course, make_notebook, make_sessionmaker

pytest_plugins = ["tests.notebook_fixtures"]


def _document(text):
    return {"type": "doc", "content": [
        {"type": "heading", "attrs": {"blockId": "h-1", "level": 1},
         "content": [{"type": "text", "text": "导数与优化"}]},
        {"type": "paragraph", "attrs": {"blockId": "p-1"},
         "content": [{"type": "text", "text": text}]},
    ]}


def _setup(session):
    books = []
    for name in ("微积分", "机器学习"):
        course = make_course(session, name)
        book = make_notebook(session, course, name + "笔记")
        write_document(session, book, _document(name + "使用函数导数描述局部变化，梯度下降沿负梯度更新参数。"),
                       expected_revision=0)
        books.append(book)
    session.commit()
    return books


def _configure(monkeypatch, engine, client):
    factory = make_sessionmaker(engine)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    monkeypatch.setattr(notebook_relations, "SessionLocal", factory)
    monkeypatch.setattr(notebook_relations, "DeepSeekClient", lambda: client)


class Client:
    configured = True

    def complete_json(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        assert all("notebook_id" in row and "block_id" in row for row in payload["sources"])
        assert "note_id" not in messages[1]["content"]
        return {"relations": [{
            "source_key": payload["sources"][0]["key"],
            "target_key": payload["targets"][0]["key"],
            "relation_type": "application", "reason": "梯度下降应用了导数描述局部变化的概念。",
        }]}


def test_automatic_links_are_versioned_idempotent_and_notebook_scoped(session, engine, monkeypatch):
    source, target = _setup(session)
    first = enqueue_notebook_relations(session, source.course_id)
    again = enqueue_notebook_relations(session, source.course_id)
    assert first.id == again.id
    session.commit()
    _configure(monkeypatch, engine, Client())
    assert jobs.claim_next_forest_job() == first.id
    jobs.process_forest_job(first.id)
    session.expire_all()
    assert session.get(ForestJob, first.id).status == "completed"
    relation = session.scalar(select(NotebookRelation))
    assert relation.source_notebook_id == source.id
    assert relation.target_notebook_id == target.id
    assert relation.source_block_id == relation.target_block_id == "h-1"
    assert relation.source_fingerprint and relation.target_fingerprint
    assert relation.origin == "ai"
    jobs.process_forest_job(first.id)
    assert len(list(session.scalars(select(NotebookRelation)))) == 1


@pytest.mark.parametrize("mode", ["missing_model", "invented_key", "body_changed"])
def test_invalid_automatic_links_never_commit(session, engine, monkeypatch, mode):
    source, _target = _setup(session)
    task = enqueue_notebook_relations(session, source.course_id)
    session.commit()

    class InvalidClient(Client):
        configured = mode != "missing_model"

        def complete_json(self, *args, **kwargs):
            result = super().complete_json(*args, **kwargs)
            if mode == "invented_key":
                result["relations"][0]["target_key"] = "not-in-input"
            else:
                write_document(session, source, _document("用户已经修改了此处正文"), expected_revision=1)
                session.commit()
            return result

    _configure(monkeypatch, engine, InvalidClient())
    assert jobs.claim_next_forest_job() == task.id
    jobs.process_forest_job(task.id)
    session.expire_all()
    assert session.get(ForestJob, task.id).status == "failed"
    assert session.scalar(select(NotebookRelation)) is None


def test_relation_job_requires_live_body_in_two_courses(session):
    book = make_notebook(session, make_course(session))
    write_document(session, book, _document("只有一门课程的正文"), expected_revision=0)
    assert enqueue_notebook_relations(session, book.course_id) is None


def test_generation_enqueues_notebook_relations_automatically(session, engine, monkeypatch):
    from app.api.v1.generation import create_generation_job
    from app.schemas.generation import NotebookGenerationCreate
    from app.workers import notebook_generation_worker
    from tests.notebook_fixtures import make_asset, persist_ir

    source, _target = _setup(session)
    asset = make_asset(session, source)
    persist_ir(session, source, asset)
    created = create_generation_job(source.id, NotebookGenerationCreate(asset_ids=[asset.id]),
                                    "auto-relations", session)
    monkeypatch.setattr(notebook_generation_worker, "SessionLocal", make_sessionmaker(engine))
    assert notebook_generation_worker.claim_next_generation_job() == created["id"]
    notebook_generation_worker.process_generation_job(created["id"])
    session.expire_all()
    task = session.scalar(select(ForestJob).where(ForestJob.kind == "notebook_relations"))
    assert task is not None and task.status == "pending"
    assert "极限" in task.source_snapshot_json


def test_retry_commits_pending_state_and_keeps_attempt_identity(session, engine):
    from sqlalchemy.orm import Session

    from app.api.v1.forest_imports import retry_forest_job

    source, _target = _setup(session)
    task = enqueue_notebook_relations(session, source.course_id)
    task.status = "failed"
    task.attempt_count = 2
    session.commit()
    retry_forest_job(task.id, session)
    with Session(engine) as independent:
        persisted = independent.get(ForestJob, task.id)
        assert persisted.status == "pending"
        assert persisted.attempt_count == 2


def test_deleted_automatic_relation_is_not_recreated(session, engine, monkeypatch):
    from app.api.v1.notebook import delete_notebook_relation
    source, target = _setup(session)
    first = enqueue_notebook_relations(session, source.course_id)
    session.commit()
    _configure(monkeypatch, engine, Client())
    jobs.claim_next_forest_job()
    jobs.process_forest_job(first.id)
    session.expire_all()
    relation = session.scalar(select(NotebookRelation))
    delete_notebook_relation(source.id, relation.id, session)
    write_document(session, target, _document('更新后正文仍然讨论导数与梯度下降。'), expected_revision=1)
    session.commit()
    next_job = enqueue_notebook_relations(session, source.course_id)
    session.commit()
    jobs.claim_next_forest_job()
    jobs.process_forest_job(next_job.id)
    session.expire_all()
    assert session.scalar(select(NotebookRelation)) is None
