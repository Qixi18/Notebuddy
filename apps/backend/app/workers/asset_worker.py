"""Background processing for image Assets, separate from Material parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.database import SessionLocal
from app.db.model_utils import new_id
from app.db.models import Asset, AssetParseResult, AssetProcessingJob
from app.notes.assets import storage_path
from app.parsers.ocr import OCRUnavailable, ocr_image


def claim_next_asset_job() -> str | None:
    with SessionLocal() as db:
        job_id = db.scalar(select(AssetProcessingJob.id).where(
            AssetProcessingJob.status == "pending",
        ).order_by(AssetProcessingJob.created_at, AssetProcessingJob.id).limit(1))
        if job_id is None:
            return None
        result = db.execute(update(AssetProcessingJob).where(
            AssetProcessingJob.id == job_id,
            AssetProcessingJob.status == "pending",
        ).values(status="processing", attempt_count=AssetProcessingJob.attempt_count + 1,
                 updated_at=datetime.now(UTC)))
        db.commit()
        return job_id if result.rowcount == 1 else None


def process_asset_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(AssetProcessingJob, job_id)
        if job is None or job.status != "processing":
            return
        asset = db.get(Asset, job.asset_id)
        if asset is None or asset.state != "ready":
            job.status = "failed"
            job.error_code = "asset_unavailable"
            job.error_message = "原始图片资源当前不可用"
            job.finished_at = datetime.now(UTC)
            job.updated_at = job.finished_at
            db.add(AssetParseResult(
                id=new_id(), asset_id=job.asset_id, job_id=job.id,
                provider="none", parser_version="image-parse-v1", status="failed",
                result_json=None, warnings_json=json.dumps([job.error_message], ensure_ascii=False),
                created_at=job.finished_at, completed_at=job.finished_at,
            ))
            db.commit()
            return
        try:
            text, provider, confidence = ocr_image(storage_path(asset), page_number=1)
            result = {"text": text, "confidence": confidence, "kind": "ocr_text"}
            warnings = [] if text else ["OCR 未识别到文字；图片仍保留，可人工查看或重试"]
            job.status = "completed" if text else "completed_with_warnings"
            job.error_code = None
            job.error_message = None
        except OCRUnavailable as exc:
            provider = "tesseract"
            result = None
            warnings = [str(exc)]
            job.status = "failed"
            job.error_code = "ocr_unavailable" if "未启用" in str(exc) or "依赖未安装" in str(exc) else "ocr_failed"
            job.error_message = str(exc)
        except Exception as exc:  # provider/parser boundary; preserve the input Asset.
            provider = "tesseract"
            result = None
            warnings = [f"图片解析失败：{type(exc).__name__}"]
            job.status = "failed"
            job.error_code = "image_parse_failed"
            job.error_message = warnings[0]
        finished = datetime.now(UTC)
        job.finished_at = finished
        job.updated_at = finished
        db.add(AssetParseResult(
            id=new_id(), asset_id=asset.id, job_id=job.id, provider=provider,
            parser_version="image-parse-v1", status=job.status,
            result_json=json.dumps(result, ensure_ascii=False) if result is not None else None,
            warnings_json=json.dumps(warnings, ensure_ascii=False),
            created_at=finished, completed_at=finished,
        ))
        db.commit()
