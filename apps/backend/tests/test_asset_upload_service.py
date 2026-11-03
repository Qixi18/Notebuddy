from __future__ import annotations

import base64
from io import BytesIO

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Asset, NotebookGenerationInput, NotebookUploadBatch
from app.services.asset_uploads import upload_notebook_asset
from app.services.errors import ApplicationError
from tests.notebook_fixtures import make_course, make_notebook

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
    "lS8AAAAASUVORK5CYII="
)

pytest_plugins = ["tests.notebook_fixtures"]


def test_source_image_upload_registers_the_parse_job_and_generation_input(
    session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    notebook = make_notebook(session, make_course(session), "图片资料笔记")

    result = upload_notebook_asset(
        session,
        notebook_id=notebook.id,
        filename="figure.png",
        source=BytesIO(PNG_1PX),
        image_data=PNG_1PX,
        media_type="image/png",
        upload_batch_id=None,
        processing_route="standard",
    )

    row = session.scalar(select(NotebookGenerationInput).where(
        NotebookGenerationInput.asset_id == result.asset.id,
    ))
    batch = session.get(NotebookUploadBatch, result.upload_batch_id)
    assert result.job is not None
    assert row is not None
    assert row.parse_kind == "image"
    assert row.parse_job_id == result.job.id
    assert row.status == "waiting_parse"
    assert batch is not None and batch.closed_at is not None
    assert result.asset.state == "ready"


def test_failed_image_upload_does_not_leave_an_empty_batch_or_asset(session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    notebook = make_notebook(session, make_course(session), "图片资料笔记")

    with pytest.raises(ApplicationError) as error:
        upload_notebook_asset(
            session,
            notebook_id=notebook.id,
            filename="broken.png",
            source=BytesIO(b"not-an-image"),
            image_data=b"not-an-image",
            media_type="image/png",
            upload_batch_id=None,
            processing_route="standard",
        )

    assert error.value.status_code == 422
    assert session.scalar(select(NotebookUploadBatch.id)) is None
    assert session.scalar(select(Asset.id)) is None
