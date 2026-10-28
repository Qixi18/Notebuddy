from sqlalchemy import select

from app.api.v1.materials import get_document_coverage
from app.db.models import AssetProcessingJob, DocumentBlock, NotebookAsset, NotebookBlockSource
from app.document_processing.service import create_parse_run, execute_parse_run
from tests.notebook_fixtures import make_asset, make_notebook, persist_ir

pytest_plugins = ["tests.notebook_fixtures"]


def test_coverage_uses_source_database_id_and_active_status(session, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.db.database import get_db
    from app.main import app

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    book = make_notebook(session, None)
    asset = make_asset(session, book)
    source = tmp_path / asset.storage_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test")
    run = persist_ir(session, book, asset)
    blocks = list(session.scalars(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id,
    ).order_by(DocumentBlock.order)))
    link = NotebookBlockSource(
        notebook_id=book.id, block_id="editor-block", parse_run_id=run.id,
        document_block_id=blocks[0].id, page_number=1, status="active",
    )
    session.add(link)
    session.flush()
    result = get_document_coverage(asset.id, notebook_id=book.id, run_id=run.id, db=session)
    assert result["cited_blocks"] == 1
    assert result["blocks"][0]["citations"][0]["block_id"] == "editor-block"
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/assets/{asset.id}/document/coverage",
                                  params={"notebook_id": book.id, "run_id": run.id})
            assert response.status_code == 200
            assert response.json()["cited_blocks"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
    link.status = "stale"
    session.flush()
    assert get_document_coverage(asset.id, notebook_id=book.id, run_id=run.id, db=session)["cited_blocks"] == 0


def test_completed_run_cannot_be_executed_again(session):
    import pytest

    book = make_notebook(session, None)
    asset = make_asset(session, book)
    run = persist_ir(session, book, asset)
    assert create_parse_run(session, asset=asset).id == run.id
    with pytest.raises(Exception, match="已完成|completed"):
        execute_parse_run(session, run.id)
    session.refresh(run)
    assert run.status == "completed" and run.is_current


def test_image_job_reuses_completed_run_and_retry_preserves_old_on_failure(
    session, engine, tmp_path, monkeypatch,
):
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.document_processing.service import current_run
    from app.workers import asset_worker

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(asset_worker, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    book = make_notebook(session, None)
    asset = make_asset(session, book, media_type="image", extension=".png")
    source = tmp_path / asset.storage_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    run = persist_ir(session, book, asset)
    owner = session.scalar(select(NotebookAsset).where(NotebookAsset.asset_id == asset.id))
    original_id = session.scalar(select(DocumentBlock.id).where(
        DocumentBlock.parse_run_id == run.id,
    ))
    job = AssetProcessingJob(asset_id=asset.id, notebook_id=book.id, owner_link_id=owner.id,
                             kind="image_parse", status="processing")
    session.add(job)
    session.commit()

    def fail(*args, **kwargs):
        raise RuntimeError("deliberate parse failure")

    monkeypatch.setattr(asset_worker, "execute_parse_run", fail)
    asset_worker.process_asset_job(job.id)
    session.expire_all()
    assert session.get(AssetProcessingJob, job.id).status == "completed"
    assert current_run(session, asset.id).id == run.id

    retry = AssetProcessingJob(asset_id=asset.id, notebook_id=book.id, owner_link_id=owner.id,
                               kind="image_reparse", status="processing")
    session.add(retry)
    session.commit()
    asset_worker.process_asset_job(retry.id)
    session.expire_all()
    assert session.get(AssetProcessingJob, retry.id).status == "failed"
    assert current_run(session, asset.id).id == run.id
    assert session.get(DocumentBlock, original_id) is not None
