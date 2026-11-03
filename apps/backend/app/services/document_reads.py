"""Application queries for persisted document-processing results."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Asset,
    AssetParseResult,
    DocumentBlock,
    DocumentPage,
    DocumentParseRun,
    Material,
    Notebook,
    NotebookAsset,
    NotebookBlockSource,
    NotebookSection,
)
from app.document_processing.ir import QualityReport
from app.document_processing.service import (
    current_run as current_parse_run,
)
from app.document_processing.service import (
    latest_run as latest_parse_run,
)
from app.document_processing.service import (
    load_ir,
    page_render,
)
from app.notes.assets import AssetUnavailable, assert_notebook_asset, storage_path
from app.services.errors import ApplicationError


def list_asset_parse_results(db: Session, asset_id: str) -> list[AssetParseResult]:
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if owner is None:
        raise ApplicationError(404, "资源不存在")
    return list(db.scalars(select(AssetParseResult).where(
        AssetParseResult.asset_id == asset_id,
    ).order_by(AssetParseResult.created_at.desc())).all())


def list_asset_parse_runs(
    db: Session, asset_id: str, notebook_id: str | None = None,
) -> list[dict]:
    ensure_asset_access(db, asset_id, notebook_id)
    runs = db.scalars(select(DocumentParseRun).where(
        DocumentParseRun.asset_id == asset_id,
    ).order_by(DocumentParseRun.created_at.desc())).all()
    return [_run_payload(run) for run in runs]


def get_asset_document(
    db: Session, asset_id: str, notebook_id: str | None = None,
) -> dict:
    ensure_asset_access(db, asset_id, notebook_id)
    run = current_parse_run(db, asset_id)
    if run is None:
        latest = latest_parse_run(db, asset_id)
        if latest is not None and latest.status == "failed":
            raise ApplicationError(409, {
                "code": latest.error_code or "parse_failed",
                "message": latest.error_message or "解析失败",
                "run_id": latest.id,
            })
        raise ApplicationError(404, "该资料还没有完成的解析版本")
    return _document_payload(db, run)


def get_asset_document_run(
    db: Session, asset_id: str, run_id: str, notebook_id: str | None = None,
) -> dict:
    ensure_asset_access(db, asset_id, notebook_id)
    run = db.get(DocumentParseRun, run_id)
    if run is None or run.asset_id != asset_id:
        raise ApplicationError(404, "解析版本不存在")
    if run.status != "completed":
        raise ApplicationError(409, {
            "code": run.error_code or "parse_incomplete",
            "message": run.error_message or "解析尚未完成",
            "run_id": run.id,
        })
    return _document_payload(db, run)


def get_document_page_evidence(
    db: Session,
    asset_id: str,
    page_number: int,
    *,
    notebook_id: str | None = None,
    run_id: str | None = None,
) -> list[dict]:
    ensure_asset_access(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise ApplicationError(404, "该资料还没有完成的解析版本")
    document = load_ir(db, run)
    page = next((item for item in document.pages if item.page_number == page_number), None)
    if page is None:
        raise ApplicationError(404, "页面不存在")
    payloads = []
    for block in page.blocks:
        payload = _block_payload(block)
        if block.figure and block.figure.image_key:
            payload["figure"]["image_key"] = _figure_image_url(
                run.asset_id, run.id, block.figure.image_key,
            )
        payloads.append(payload)
    return payloads


def get_legacy_material_pages(db: Session, material_id: str) -> list[dict]:
    """Preserve the legacy Material page projection over the current DocumentIR."""
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is not None:
        raise ApplicationError(404, "资料不存在")
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_parse_run(db, asset.id) if asset is not None else None
    if run is None:
        return []
    document = load_ir(db, run)
    return [_legacy_page_payload(page, material_id) for page in document.pages]


def get_legacy_material_page_evidence(
    db: Session, material_id: str, page_number: int,
) -> dict:
    material = db.get(Material, material_id)
    if material is None or material.deleted_at is not None:
        raise ApplicationError(404, "资料不存在")
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_parse_run(db, asset.id) if asset is not None else None
    if run is None:
        raise ApplicationError(404, "资料还没有完成的解析版本")
    document = load_ir(db, run)
    page = next((item for item in document.pages if item.page_number == page_number), None)
    if page is None:
        raise ApplicationError(404, "资料位置不存在")

    rows = db.scalars(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id,
    )).all()
    db_id_by_block = {row.block_id: row.id for row in rows}
    citations: dict[str, list[tuple[str, str]]] = {}
    links = db.execute(
        select(NotebookBlockSource.document_block_id, NotebookBlockSource.block_id,
               Notebook.id, Notebook.title, NotebookSection.heading)
        .join(Notebook, Notebook.id == NotebookBlockSource.notebook_id)
        .outerjoin(NotebookSection, (NotebookSection.notebook_id == NotebookBlockSource.notebook_id)
                   & (NotebookSection.block_id == NotebookBlockSource.block_id))
        .where(NotebookBlockSource.parse_run_id == run.id)
    ).all()
    for document_block_id, _body_block_id, notebook_id, title, heading in links:
        citations.setdefault(document_block_id, []).append((notebook_id, heading or title))
    blocks: list[dict] = []
    note_ids: list[str] = []
    note_titles: list[str] = []
    for block in sorted(page.blocks, key=lambda item: (item.order, item.global_order)):
        linked = citations.get(db_id_by_block.get(block.block_id, ""), [])
        block_note_ids = list(dict.fromkeys(item[0] for item in linked))
        block_note_titles = list(dict.fromkeys(item[1] for item in linked))
        for notebook_id in block_note_ids:
            if notebook_id not in note_ids:
                note_ids.append(notebook_id)
        for title in block_note_titles:
            if title not in note_titles:
                note_titles.append(title)
        blocks.append({
            "id": block.block_id, "page_id": page.page_id,
            "block_type": block.type, "content": block.text,
            "position": block.order, "font_size": None, "is_bold": False,
            "object_id": None,
            "location_label": block.source.location_label if block.source else None,
            "extraction_method": block.extraction, "confidence": block.confidence,
            "warning": "；".join(block.warnings) or None,
            "note_ids": block_note_ids, "note_titles": block_note_titles,
        })
    payload = _legacy_page_payload(page, material_id)
    payload.update({"blocks": blocks, "note_ids": note_ids, "note_titles": note_titles})
    return payload


def _legacy_page_payload(page, material_id: str) -> dict:
    heading = next((block.text for block in sorted(page.blocks, key=lambda item: item.order)
                    if block.type == "heading" and block.text.strip()), None)
    status = "parsed"
    if page.status == "needs_ocr":
        status = "ocr_candidate"
    elif page.status in {"failed", "empty"}:
        status = page.status
    return {
        "id": page.page_id, "material_id": material_id,
        "page_number": page.page_number, "title": heading,
        "raw_text": page.text, "parse_status": status,
        "warning": "；".join(page.warnings) or None,
        "location_type": "page", "location_label": f"第 {page.page_number} 页",
        "stable_location_key": f"page:{page.page_number}",
        "extraction_method": page.extraction, "confidence": page.confidence,
    }


def resolve_document_page_render(
    db: Session,
    asset_id: str,
    page_number: int,
    *,
    notebook_id: str | None = None,
    run_id: str | None = None,
) -> tuple[Path, str]:
    """Resolve a page render and commit any render-cache bookkeeping."""
    asset = ensure_asset_access(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise ApplicationError(404, "该资料还没有完成的解析版本")
    if (asset.extension or "").lower() != ".pdf":
        try:
            path = storage_path(asset)
        except AssetUnavailable as exc:
            raise ApplicationError(404, str(exc)) from exc
        return path, asset.mime_type
    path = page_render(db, run, page_number)
    if path is None or not path.is_file():
        raise ApplicationError(404, "该页无法渲染")
    db.commit()
    return path, "image/png"


def resolve_document_figure_image(
    db: Session,
    asset_id: str,
    image_token: str,
    *,
    notebook_id: str | None = None,
    run_id: str | None = None,
) -> tuple[Path, str]:
    ensure_asset_access(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise ApplicationError(404, "解析版本不存在")
    document = load_ir(db, run)
    figure_key = next((
        block.figure.image_key
        for page in document.pages
        for block in page.blocks
        if block.figure and block.figure.image_key
        and Path(block.figure.image_key).name.rsplit(".", 1)[0] == image_token
    ), None)
    if not figure_key:
        raise ApplicationError(404, "图片证据不存在")
    root = settings.data_dir.resolve()
    path = (root / figure_key).resolve()
    if not path.is_relative_to(root) or path == root or not path.is_file():
        raise ApplicationError(404, "图片证据不可用")
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return path, media_type


def get_document_coverage(
    db: Session,
    asset_id: str,
    *,
    notebook_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    asset = ensure_asset_access(db, asset_id, notebook_id)
    run = _selected_completed_run(db, asset_id, run_id)
    if run is None:
        raise ApplicationError(404, "该资料还没有完成的解析版本")
    rows = db.execute(
        select(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(DocumentBlock.parse_run_id == run.id)
    ).all()
    links = db.execute(
        select(NotebookBlockSource, Notebook)
        .join(Notebook, Notebook.id == NotebookBlockSource.notebook_id)
        .where(NotebookBlockSource.parse_run_id == run.id,
               NotebookBlockSource.status == "active")
    ).all()
    cited: dict[str, list[dict]] = {}
    for link, notebook in links:
        if notebook_id and notebook.id != notebook_id:
            continue
        cited.setdefault(link.document_block_id, []).append({
            "notebook_id": notebook.id,
            "notebook_title": notebook.title,
            "block_id": link.block_id,
            "page_number": link.page_number,
        })
    blocks = []
    for row, page_number in rows:
        try:
            table = json.loads(row.table_json or "null")
            figure = json.loads(row.figure_json or "null")
        except (TypeError, ValueError):
            table = figure = None
        if not (
            row.text.strip()
            or (row.latex or "").strip()
            or (isinstance(table, dict) and table.get("rows"))
            or (isinstance(figure, dict) and figure.get("image_key"))
        ):
            continue
        blocks.append({
            "block_id": row.block_id,
            "page_number": page_number,
            "quote": row.text[:300],
            "citations": cited.get(row.id, []),
        })
    cited_total = sum(1 for block in blocks if block["citations"])
    pages: dict[int, dict[str, int]] = {}
    for block in blocks:
        bucket = pages.setdefault(block["page_number"], {"total": 0, "cited": 0})
        bucket["total"] += 1
        if block["citations"]:
            bucket["cited"] += 1
    return {
        "asset_id": asset.id,
        "asset_name": asset.original_name,
        "parse_run_id": run.id,
        "total_blocks": len(blocks),
        "cited_blocks": cited_total,
        "pages": [{"page_number": number, **counts} for number, counts in sorted(pages.items())],
        "blocks": blocks,
    }


def ensure_asset_access(db: Session, asset_id: str, notebook_id: str | None = None) -> Asset:
    if notebook_id:
        try:
            return assert_notebook_asset(db, asset_id, notebook_id)
        except AssetUnavailable as exc:
            raise ApplicationError(404, str(exc)) from exc
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ApplicationError(404, "资源不存在")
    return asset


def _selected_completed_run(
    db: Session, asset_id: str, run_id: str | None,
) -> DocumentParseRun | None:
    run = current_parse_run(db, asset_id) if run_id is None else db.get(DocumentParseRun, run_id)
    if run is not None and (run.asset_id != asset_id or run.status != "completed"):
        raise ApplicationError(404, "解析版本不存在或尚未完成")
    return run


def _run_payload(run: DocumentParseRun) -> dict:
    return {
        "id": run.id,
        "asset_id": run.asset_id,
        "doc_type": run.doc_type,
        "status": run.status,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "config_version": run.config_version,
        "is_current": run.is_current,
        "fingerprint": run.fingerprint,
        "page_count": run.page_count,
        "text_chars": run.text_chars,
        "quality_status": run.quality_status,
        "quality": QualityReport.from_dict(json.loads(run.quality_json or "{}")).to_dict(),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def _document_payload(db: Session, run: DocumentParseRun) -> dict:
    document = load_ir(db, run)
    pages = [{
        "page_number": page.page_number,
        "status": page.status,
        "extraction": page.extraction,
        "width": page.width,
        "height": page.height,
        "rotation": page.rotation,
        "confidence": page.confidence,
        "warnings": page.warnings,
        "text_chars": len(page.text.strip()),
        "render_url": f"/api/v1/assets/{run.asset_id}/document/pages/{page.page_number}/render",
    } for page in document.pages]
    sections = [{
        "section_id": section.section_id,
        "title": section.title,
        "level": section.level,
        "page_start": section.page_start,
        "page_end": section.page_end,
        "block_ids": section.block_ids,
    } for section in document.sections]
    return {"run": _run_payload(run), "pages": pages, "sections": sections}


def _block_payload(block) -> dict:
    return {
        "block_id": block.block_id,
        "page_number": block.page_number,
        "type": block.type,
        "level": block.level,
        "text": block.text,
        "latex": block.latex,
        "table": block.table.to_dict() if block.table else None,
        "figure": block.figure.to_dict() if block.figure else None,
        "bbox": block.bbox,
        "extraction": block.extraction,
        "confidence": block.confidence,
        "warnings": block.warnings,
    }


def _figure_image_url(asset_id: str, run_id: str, image_key: str) -> str:
    token = Path(image_key).name.rsplit(".", 1)[0]
    return f"/api/v1/assets/{asset_id}/document/figures/{token}?run_id={run_id}"
