from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db.models import (
    NotebookGenerationInput,
    NotebookGenerationJob,
    NotebookUploadBatch,
)
from app.services.errors import ApplicationError
from app.services.generation_jobs import cancel_generation_job, retry_generation_job
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


def _job(session, notebook, status: str):
    job = NotebookGenerationJob(
        notebook_id=notebook.id, idempotency_key=f"job-{status}",
        request_fingerprint="f" * 64, status=status, base_document_revision=0,
        input_snapshot_json=json.dumps({
            "base_document_revision": 0,
            "current_document": {"type": "doc", "content": []},
            "current_outline": [], "sources": [],
        }), model="test", prompt_version="test", attempt_count=2,
    )
    session.add(job)
    session.flush()
    return job


@pytest.mark.parametrize("status", ["failed", "conflict", "cancelled"])
def test_retry_allowed_states_refresh_revision_without_rewinding_attempts(session, status):
    notebook = make_notebook(session, make_course(session), "笔记")
    job = _job(session, notebook, status)
    notebook.document_revision = 7
    session.commit()

    result = retry_generation_job(session, notebook.id, job.id)

    assert result["status"] == "pending"
    assert result["attempt_count"] == 2
    assert result["base_document_revision"] == 7
    snapshot = json.loads(session.get(NotebookGenerationJob, job.id).input_snapshot_json)
    assert snapshot["base_document_revision"] == 7
    assert snapshot["current_document"] == json.loads(notebook.document_json)["doc"]


@pytest.mark.parametrize("status", ["pending", "processing", "completed", "cancel_requested"])
def test_retry_rejects_non_retryable_states(session, status):
    notebook = make_notebook(session, make_course(session), "笔记")
    job = _job(session, notebook, status)
    session.commit()

    with pytest.raises(ApplicationError) as error:
        retry_generation_job(session, notebook.id, job.id)

    assert error.value.status_code == 409
    session.refresh(job)
    assert job.status == status


def test_pending_cancel_updates_linked_generation_input(session):
    from tests.notebook_fixtures import make_asset

    notebook = make_notebook(session, make_course(session), "笔记")
    job = _job(session, notebook, "pending")
    batch = NotebookUploadBatch(id="batch-1", notebook_id=notebook.id)
    session.add(batch)
    session.flush()
    asset = make_asset(session, notebook)
    row = NotebookGenerationInput(
        notebook_id=notebook.id, asset_id=asset.id, batch_id=batch.id,
        parse_kind="document", status="generating", generation_job_id=job.id,
    )
    session.add(row)
    session.commit()

    result = cancel_generation_job(session, notebook.id, job.id)

    assert result["status"] == "cancelled"
    session.refresh(row)
    assert row.status == "generation_failed"
    assert row.error_code == "cancelled"


def test_processing_cancel_requests_worker_cancellation_and_completed_is_immutable(session):
    notebook = make_notebook(session, make_course(session), "笔记")
    processing = _job(session, notebook, "processing")
    completed = _job(session, notebook, "completed")
    session.commit()

    assert cancel_generation_job(session, notebook.id, processing.id)["status"] == "cancel_requested"
    with pytest.raises(ApplicationError) as error:
        cancel_generation_job(session, notebook.id, completed.id)
    assert error.value.status_code == 409
    session.refresh(completed)
    assert completed.status == "completed"


def test_two_retries_of_same_failed_job_only_one_can_win(session):
    notebook = make_notebook(session, make_course(session), "笔记")
    job = _job(session, notebook, "failed")
    session.commit()

    retry_generation_job(session, notebook.id, job.id)
    with pytest.raises(ApplicationError) as error:
        retry_generation_job(session, notebook.id, job.id)
    assert error.value.status_code == 409
    assert session.scalar(select(NotebookGenerationJob.status).where(
        NotebookGenerationJob.id == job.id,
    )) == "pending"
