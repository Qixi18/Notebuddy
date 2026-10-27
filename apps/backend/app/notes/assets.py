"""Notebook-owned resource metadata and path-safe local file access."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Asset,
    AssetProcessingJob,
    Material,
    Notebook,
    NotebookAsset,
    NotebookCoverAsset,
    NotebookGenerationCandidate,
    NotebookGenerationJob,
    NotebookRevisionAsset,
    ProcessingJob,
)
from app.notes.document import attachment_ids, load_document


class AssetUnavailable(FileNotFoundError):
    pass


ASSET_ORPHAN_GRACE_PERIOD = timedelta(days=1)


def storage_path(asset: Asset) -> Path:
    """Resolve a database storage key under the configured data directory."""
    root = settings.data_dir.resolve()
    candidate = root / asset.storage_key
    try:
        path = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise AssetUnavailable("资源存储路径不可访问") from exc
    if not path.is_relative_to(root) or path == root:
        raise AssetUnavailable("资源存储路径无效")
    current = candidate
    while current != root:
        if current.is_symlink():
            raise AssetUnavailable("资源存储路径包含符号链接")
        current = current.parent
    if not path.is_file():
        raise AssetUnavailable("资源文件不存在")
    return path


def assert_notebook_asset(db: Session, asset_id: str, notebook_id: str) -> Asset:
    """Require the active owner and prevent cross-Notebook resource access."""
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        raise AssetUnavailable("笔记不存在或已删除")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.state != "ready":
        raise AssetUnavailable("资源不存在或不可用")
    owner = db.scalar(select(NotebookAsset.id).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if owner is None:
        raise AssetUnavailable("资源不属于该笔记")
    storage_path(asset)
    return asset


def assets_referenced_by_revision(db: Session, revision_id: str) -> set[str]:
    return set(db.scalars(select(NotebookRevisionAsset.asset_id).where(
        NotebookRevisionAsset.revision_id == revision_id,
    )).all())


def notebook_generation_references_asset(db: Session, notebook_id: str, asset_id: str) -> bool:
    jobs = db.scalars(select(NotebookGenerationJob).where(
        NotebookGenerationJob.notebook_id == notebook_id,
        NotebookGenerationJob.status.in_(
            ("pending", "processing", "cancel_requested", "candidate_ready", "failed", "conflict")
        ),
    )).all()
    for job in jobs:
        if job.status in {"failed", "conflict"} and job.attempt_count >= 3:
            continue
        try:
            snapshot = json.loads(job.input_snapshot_json)
        except (TypeError, ValueError):
            return True
        if asset_id in {source.get("asset_id") for source in snapshot.get("sources", [])
                        if isinstance(source, dict)}:
            return True
    return False


def notebook_candidate_references_asset(db: Session, notebook_id: str, asset_id: str) -> bool:
    candidates = db.scalars(select(NotebookGenerationCandidate).join(
        NotebookGenerationJob, NotebookGenerationJob.id == NotebookGenerationCandidate.job_id,
    ).where(
        NotebookGenerationCandidate.notebook_id == notebook_id,
        NotebookGenerationCandidate.status == "pending_review",
    )).all()
    for candidate in candidates:
        try:
            if asset_id in attachment_ids(json.loads(candidate.document_json)):
                return True
        except (TypeError, ValueError):
            return True
    return False


def has_live_asset_references(db: Session, asset: Asset, notebook_id: str) -> bool:
    if db.scalar(select(NotebookCoverAsset.notebook_id).where(
        NotebookCoverAsset.asset_id == asset.id,
    ).limit(1)):
        return True
    notebook = db.get(Notebook, notebook_id)
    if notebook is not None:
        current = load_document(notebook.document_json)
        if current.warning or asset.id in attachment_ids(current.content):
            return True
    if db.scalar(select(NotebookRevisionAsset.id).where(
        NotebookRevisionAsset.notebook_id == notebook_id,
        NotebookRevisionAsset.asset_id == asset.id,
    ).limit(1)):
        return True
    if db.scalar(select(AssetProcessingJob.id).where(
        AssetProcessingJob.asset_id == asset.id,
        AssetProcessingJob.status.in_(("pending", "processing", "cancel_requested")),
    ).limit(1)):
        return True
    if db.scalar(select(ProcessingJob.id).join(Material, Material.id == ProcessingJob.material_id).where(
        Material.asset_id == asset.id,
        ProcessingJob.status.in_(("pending", "processing", "cancel_requested")),
    ).limit(1)):
        return True
    return (
        notebook_candidate_references_asset(db, notebook_id, asset.id)
        or notebook_generation_references_asset(db, notebook_id, asset.id)
    )


def _has_active_asset_job(db: Session, asset_id: str) -> bool:
    return bool(db.scalar(select(AssetProcessingJob.id).where(
        AssetProcessingJob.asset_id == asset_id,
        AssetProcessingJob.status.in_(("pending", "processing", "cancel_requested")),
    ).limit(1)) or db.scalar(select(ProcessingJob.id).join(
        Material, Material.id == ProcessingJob.material_id,
    ).where(
        Material.asset_id == asset_id,
        ProcessingJob.status.in_(("pending", "processing", "cancel_requested")),
    ).limit(1)))


def _detach_all_notebook_links(db: Session, notebook_id: str, asset_id: str, now: datetime) -> None:
    for link in db.scalars(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.detached_at.is_(None),
    )).all():
        link.detached_at = now


def remove_notebook_asset(db: Session, notebook_id: str, asset_id: str) -> str:
    """Detach all local uses; defer physical cleanup and protect retained refs."""
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.notebook_id == notebook_id,
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    asset = db.get(Asset, asset_id)
    if owner is None or asset is None:
        raise AssetUnavailable("笔记资源不存在")
    current = load_document(db.get(Notebook, notebook_id).document_json)
    if current.warning or asset_id in attachment_ids(current.content):
        raise AssetUnavailable("请先从当前正文移除该图片，再移除资源")
    history_ref = db.scalar(select(NotebookRevisionAsset.id).where(
        NotebookRevisionAsset.notebook_id == notebook_id,
        NotebookRevisionAsset.asset_id == asset_id,
    ).limit(1))
    retained_ref = history_ref or has_live_asset_references(db, asset, notebook_id)
    now = datetime.now(UTC)
    _detach_all_notebook_links(db, notebook_id, asset_id, now)
    if asset.state not in {"missing", "deleted", "quarantined"}:
        asset.state = "ready"
    db.commit()
    if asset.state == "missing":
        return "missing"
    if asset.state == "deleted":
        return "deleted"
    if history_ref:
        return "retained_for_history"
    if retained_ref or _has_active_asset_job(db, asset_id):
        return "retained_for_processing"
    return "detached"


def collect_detached_assets(db: Session, *, limit: int = 50) -> int:
    rows = db.execute(select(NotebookAsset, Asset).join(
        Asset, Asset.id == NotebookAsset.asset_id,
    ).where(
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_not(None),
        NotebookAsset.detached_at <= datetime.now(UTC) - ASSET_ORPHAN_GRACE_PERIOD,
        Asset.state.in_(("ready", "missing", "quarantined", "delete_pending")),
    ).order_by(NotebookAsset.detached_at).limit(limit)).all()
    deleted = 0
    for owner, asset in rows:
        active_link = db.scalar(select(NotebookAsset.id).where(
            NotebookAsset.asset_id == asset.id,
            NotebookAsset.detached_at.is_(None),
        ).limit(1))
        if active_link:
            continue
        if has_live_asset_references(db, asset, owner.notebook_id):
            continue
        if asset.state in {"missing", "deleted"}:
            asset.state = "deleted"
            db.commit()
            deleted += 1
            continue
        asset.state = "delete_pending"
        db.commit()
        try:
            path = storage_path(asset)
        except AssetUnavailable as exc:
            if "文件不存在" in str(exc):
                asset.state = "deleted"
                db.commit()
                deleted += 1
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        asset.state = "deleted"
        db.commit()
        deleted += 1
    return deleted
