from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AssetProcessingJob, NotebookAsset
from app.services.asset_processing import retry_asset_parse
from app.services.errors import ApplicationError
from tests.notebook_fixtures import make_asset, make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


def _image_and_owner(session):
    notebook = make_notebook(session, make_course(session), "图片笔记")
    asset = make_asset(session, notebook, "扫描页.png", media_type="image", extension=".png")
    owner = session.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook.id,
        NotebookAsset.asset_id == asset.id,
        NotebookAsset.is_owner.is_(True),
    ))
    return notebook, asset, owner


def test_image_retry_creates_job_against_current_owner_link(session):
    notebook, asset, owner = _image_and_owner(session)
    result = retry_asset_parse(session, asset.id)

    assert result.status == "pending"
    assert result.kind == "image_reparse"
    assert result.notebook_id == notebook.id
    assert result.owner_link_id == owner.id
    assert result.asset_id == asset.id


def test_image_retry_rejects_active_job_without_creating_another(session):
    _notebook, asset, owner = _image_and_owner(session)
    session.add(AssetProcessingJob(
        asset_id=asset.id, notebook_id=owner.notebook_id, owner_link_id=owner.id,
        kind="image_parse", status="processing",
    ))
    session.commit()

    with pytest.raises(ApplicationError) as error:
        retry_asset_parse(session, asset.id)

    assert error.value.status_code == 409
    assert len(session.scalars(select(AssetProcessingJob).where(
        AssetProcessingJob.asset_id == asset.id,
    )).all()) == 1


def test_image_retry_stops_after_five_attempt_records(session):
    _notebook, asset, owner = _image_and_owner(session)
    session.add_all([
        AssetProcessingJob(
            asset_id=asset.id, notebook_id=owner.notebook_id, owner_link_id=owner.id,
            kind="image_reparse", status="failed",
        )
        for _ in range(5)
    ])
    session.commit()

    with pytest.raises(ApplicationError) as error:
        retry_asset_parse(session, asset.id)

    assert error.value.status_code == 409
    assert session.scalar(select(AssetProcessingJob.id).where(
        AssetProcessingJob.asset_id == asset.id,
        AssetProcessingJob.status == "pending",
    )) is None
