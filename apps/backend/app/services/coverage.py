"""Compute source-material coverage from Notebook body citations.

A source block is "cited" when at least one Notebook body block links to it via
``NotebookBlockSource``.  The old Note -> SourceRef count is no longer the
meaning of coverage.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    DocumentBlock,
    DocumentPage,
    Material,
    Notebook,
    NotebookBlockSource,
)
from app.document_processing.service import current_run


def material_coverage(db: Session, material_id: str) -> dict:
    material = db.get(Material, material_id)
    if material is None:
        return {"material_id": material_id, "total_locations": 0, "cited_locations": 0,
                "review_locations": 0, "locations": []}
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_run(db, asset.id) if asset is not None else None
    if run is None:
        return {
            "material_id": material_id, "total_locations": 0, "cited_locations": 0,
            "review_locations": 0, "locations": [],
            "quality_status": "pending", "generation_allowed": False,
            "message": "尚未完成解析",
        }
    rows = db.execute(
        select(DocumentBlock.id, DocumentBlock.block_id, DocumentPage.page_number,
               DocumentBlock.text)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .where(DocumentBlock.parse_run_id == run.id)
        .order_by(DocumentPage.page_number, DocumentBlock.global_order)
    ).all()
    links_query = (
        select(NotebookBlockSource.document_block_id, NotebookBlockSource.block_id,
               NotebookBlockSource.status, Notebook.id, Notebook.title)
        .join(Notebook, Notebook.id == NotebookBlockSource.notebook_id)
        .where(NotebookBlockSource.parse_run_id == run.id)
    )
    if material.notebook_id:
        links_query = links_query.where(NotebookBlockSource.notebook_id == material.notebook_id)
    links = db.execute(links_query).all()
    by_document_block: dict[str, list[tuple[str, str, str, str]]] = {}
    for document_block_id, body_block_id, status, notebook_id, title in links:
        by_document_block.setdefault(document_block_id, []).append(
            (notebook_id, title, body_block_id, status),
        )

    locations: dict[int, dict] = {}
    for document_block_id, _block_id, page_number, text in rows:
        citations = by_document_block.get(document_block_id, [])
        active = [item for item in citations if item[3] == "active"]
        bucket = locations.setdefault(page_number, {
            "page_id": f"page-{page_number}",
            "page_number": page_number,
            "location_type": "page",
            "location_label": f"第 {page_number} 页",
            "stable_location_key": f"pdf-page:{page_number}",
            "status": "review",
            "citation_count": 0,
            "note_ids": [],
            "note_titles": [],
            "warning": None,
            "block_count": 0,
            "cited_blocks": 0,
        })
        bucket["block_count"] += 1
        if active:
            bucket["cited_blocks"] += 1
            bucket["citation_count"] += len(active)
            for notebook_id, title, body_block_id, _status in active:
                if notebook_id not in bucket["note_ids"]:
                    bucket["note_ids"].append(notebook_id)
                if title not in bucket["note_titles"]:
                    bucket["note_titles"].append(title)
        if not text.strip():
            bucket["block_count"] -= 1
    for item in locations.values():
        item["status"] = "cited" if item["cited_blocks"] else "review"
    ordered = [locations[number] for number in sorted(locations)]
    cited = sum(1 for item in ordered if item["status"] == "cited")
    return {
        "material_id": material_id,
        "asset_id": asset.id if asset is not None else None,
        "parse_run_id": run.id,
        "quality_status": run.quality_status,
        "total_locations": len(ordered),
        "cited_locations": cited,
        "review_locations": len(ordered) - cited,
        "locations": ordered,
    }
