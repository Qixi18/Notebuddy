"""Backfill historical parse evidence into versioned Document IR.

Existing ``material_pages`` / ``page_blocks`` / ``asset_parse_results`` rows are
still valuable source evidence.  This command imports them as one immutable
ParseRun per Asset (``legacy-material-pages`` / ``legacy-asset-parse-result``)
so the unified pipeline can read historical materials without re-parsing files.

Idempotent: an Asset that already has a current completed ParseRun is skipped.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Asset, AssetParseResult, Material, MaterialPage, PageBlock
from app.document_processing.adapters.common import is_equation, looks_like_list
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    SourceSpan,
    TableData,
)
from app.document_processing.normalization.sections import build_sections
from app.document_processing.service import current_run, persist_existing_ir


def _doc_type(asset: Asset) -> str:
    extension = (asset.extension or "").lower()
    if asset.media_type == "image" or extension in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx"}.get(extension, "unknown")


def _asset_for_material(db, material: Material) -> Asset | None:
    if material.asset_id:
        asset = db.get(Asset, material.asset_id)
        if asset is not None:
            return asset
    asset = db.get(Asset, material.id)
    if asset is not None:
        return asset
    return db.scalar(select(Asset).where(
        Asset.storage_key == f"originals/{material.stored_filename}",
    ))


def _table_from_text(text: str) -> TableData | None:
    rows = [line.split(" | ") for line in text.splitlines() if line.strip()]
    if len(rows) < 2:
        return None
    width = max(len(row) for row in rows)
    return TableData(rows=[row + [""] * (width - len(row)) for row in rows], header_rows=1)


def _block_from_legacy(row: PageBlock, *, asset_id: str, page_number: int,
                       order: int, global_order: int) -> BlockIR:
    content = (row.content or "").strip()
    block_type = (row.block_type or "text").lower()
    kind = "paragraph"
    level = 0
    table = None
    figure = None
    warnings: list[str] = [row.warning] if row.warning else []
    if block_type in {"title", "heading"}:
        kind = "heading"
        level = 1 if block_type == "title" else 2
    elif block_type == "table":
        table = _table_from_text(content)
        kind = "table" if table else "paragraph"
        if table is None:
            warnings.append("旧解析表格未能结构化")
    elif block_type in {"image", "image_or_object"}:
        kind = "figure"
        figure = FigureData(kind="other", description=None, uncertain=True)
        warnings.append("历史解析中的图像未做视觉识别")
    elif is_equation(content):
        kind = "equation"
        warnings.append("历史解析公式未还原 LaTeX")
    elif looks_like_list(content):
        kind = "list"
    extraction = row.extraction_method if row.extraction_method in {
        "native_text", "ocr", "vision", "heuristic", "mixed", "none"} else "native_text"
    return BlockIR(
        block_id=f"legacy-{row.page_id[:8]}-{order + 1}",
        page_number=page_number,
        order=order,
        global_order=global_order,
        type=kind,
        level=level,
        text=content or ("表格" if kind == "table" else "图片/对象" if kind == "figure" else ""),
        table=table,
        figure=figure,
        source=SourceSpan(asset_id=asset_id, page_number=page_number,
                          location_label=row.location_label),
        extraction=extraction,
        confidence=row.confidence,
        warnings=warnings,
    )


def _material_ir(db, material: Material, asset: Asset) -> DocumentIR | None:
    pages = list(db.scalars(select(MaterialPage).where(
        MaterialPage.material_id == material.id,
        MaterialPage.is_active.is_(True),
    ).order_by(MaterialPage.page_number)).all())
    if not pages:
        return None
    page_irs: list[PageIR] = []
    global_order = 0
    for page in pages:
        blocks = list(db.scalars(select(PageBlock).where(
            PageBlock.page_id == page.id,
        ).order_by(PageBlock.position, PageBlock.id)).all())
        page_blocks = [
            _block_from_legacy(row, asset_id=asset.id, page_number=page.page_number,
                               order=index, global_order=global_order + index)
            for index, row in enumerate(blocks)
        ]
        global_order += len(page_blocks)
        status = "parsed" if page.raw_text.strip() else "empty"
        if page.parse_status == "ocr_candidate":
            status = "needs_ocr"
        elif page.parse_status == "failed":
            status = "failed"
        page_irs.append(PageIR(
            page_id=f"legacy-{page.id}",
            page_number=page.page_number,
            rotation=0,
            extraction=page.extraction_method if page.extraction_method in {
                "native_text", "ocr", "vision", "heuristic", "mixed", "none"} else "native_text",
            status=status,
            text=page.raw_text,
            confidence=page.confidence,
            warnings=[page.warning] if page.warning else [],
            blocks=page_blocks,
        ))
    document = DocumentIR(
        document_id=asset.id,
        asset_id=asset.id,
        parse_run_id=f"legacy-{asset.id[:8]}",
        doc_type=_doc_type(asset),
        file_sha256=asset.sha256,
        parser_name="legacy-material-pages",
        parser_version=material.parser_version or "phase2-1",
        config_version="legacy-backfill-v1",
        page_count=len(page_irs),
        pages=page_irs,
        warnings=["由历史 material_pages/page_blocks 回填；未重新识别原始文件"],
    )
    document.sections = build_sections(document, document_title=material.lecture_title)
    return document


def _image_ir(db, asset: Asset) -> DocumentIR | None:
    result = db.scalar(select(AssetParseResult).where(
        AssetParseResult.asset_id == asset.id,
        AssetParseResult.status.in_(("completed", "completed_with_warnings")),
    ).order_by(AssetParseResult.created_at.desc()).limit(1))
    if result is None or not result.result_json:
        return None
    try:
        payload = json.loads(result.result_json)
    except (TypeError, ValueError):
        return None
    text = str(payload.get("text") or "").strip()
    if not text:
        return None
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()] or [text]
    blocks = [
        BlockIR(
            block_id=f"legacy-{asset.id[:8]}-b{index + 1}",
            page_number=1, order=index, global_order=index, type="paragraph",
            text=paragraph, source=SourceSpan(asset_id=asset.id, page_number=1),
            extraction="ocr", confidence=result.result_json and payload.get("confidence"),
        )
        for index, paragraph in enumerate(paragraphs)
    ]
    page = PageIR(
        page_id=f"legacy-{asset.id}-p1", page_number=1, extraction="ocr",
        status="parsed", text=text, confidence=payload.get("confidence"), blocks=blocks,
    )
    document = DocumentIR(
        document_id=asset.id, asset_id=asset.id, parse_run_id=f"legacy-{asset.id[:8]}",
        doc_type="image", file_sha256=asset.sha256, parser_name="legacy-asset-parse-result",
        parser_version=result.parser_version or "image-parse-v1",
        config_version="legacy-backfill-v1", page_count=1, pages=[page],
        warnings=["由历史 AssetParseResult 回填；未重新识别原图"],
    )
    document.sections = build_sections(document, document_title=asset.original_name)
    return document


def backfill(db, *, limit: int | None = None) -> dict:
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "materials": {"imported": 0, "skipped_current": 0, "no_pages": 0, "no_asset": 0},
        "images": {"imported": 0, "skipped_current": 0, "no_result": 0, "no_asset": 0},
        "errors": [],
    }
    materials = list(db.scalars(select(Material).order_by(Material.created_at)).all())
    if limit:
        materials = materials[:limit]
    for material in materials:
        asset = _asset_for_material(db, material)
        if asset is None:
            report["materials"]["no_asset"] += 1
            continue
        if current_run(db, asset.id) is not None:
            report["materials"]["skipped_current"] += 1
            continue
        try:
            document = _material_ir(db, material, asset)
            if document is None:
                report["materials"]["no_pages"] += 1
                continue
            persist_existing_ir(db, asset=asset, document=document,
                                config={"source": "legacy_material_pages",
                                        "material_id": material.id})
            db.commit()
            report["materials"]["imported"] += 1
        except Exception as exc:
            db.rollback()
            report["errors"].append({"material_id": material.id,
                                     "error": f"{type(exc).__name__}: {exc}"})

    assets = list(db.scalars(select(Asset).where(Asset.media_type == "image")).all())
    for asset in assets:
        if current_run(db, asset.id) is not None:
            report["images"]["skipped_current"] += 1
            continue
        try:
            document = _image_ir(db, asset)
            if document is None:
                report["images"]["no_result"] += 1
                continue
            persist_existing_ir(db, asset=asset, document=document,
                                config={"source": "legacy_asset_parse_result"})
            db.commit()
            report["images"]["imported"] += 1
        except Exception as exc:
            db.rollback()
            report["errors"].append({"asset_id": asset.id,
                                     "error": f"{type(exc).__name__}: {exc}"})
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy parse evidence into Document IR")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    with SessionLocal() as db:
        report = backfill(db, limit=args.limit)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
