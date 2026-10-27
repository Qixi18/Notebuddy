"""Build the immutable generation input snapshot from Document IR.

The snapshot records ParseRun identity and IR fingerprints so a job can be
audited and retried, and carries section/block structure instead of a flat
page-concatenated string.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Asset, Notebook
from app.document_processing.ir import QualityReport
from app.document_processing.service import current_run, load_ir
from app.notes.document import load_document
from app.notes.index import node_text


class GenerationInputError(RuntimeError):
    def __init__(self, message: str, *, code: str = "generation_input_invalid",
                 details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or []


MAX_BLOCK_CHARS = 6_000
MAX_TABLE_ROWS = 40
MAX_TABLE_COLS = 12
MAX_FIGURE_CHARS = 1_500


def build_snapshot(db: Session, notebook: Notebook, asset_ids: list[str]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    failures: list[dict] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        if asset is None:
            failures.append({"asset_id": asset_id, "code": "asset_missing",
                             "message": "资料资源不存在"})
            continue
        try:
            sources.append(_source_snapshot(db, asset))
        except GenerationInputError as exc:
            failures.append({"asset_id": asset_id, "code": exc.code, "message": str(exc)})
    if failures:
        message = "部分资料尚不能用于生成：" + "；".join(item["message"] for item in failures)
        code = failures[0]["code"] if len(failures) == 1 else "generation_input_invalid"
        raise GenerationInputError(message, code=code, details=failures)
    current = load_document(notebook.document_json)
    return {
        "notebook_id": notebook.id,
        "notebook_title": notebook.title,
        "base_document_revision": notebook.document_revision,
        "current_document": current.content,
        "current_outline": current_outline(current.content),
        "sources": sources,
        "generator": settings.notebook_generator,
        "batch_chars": settings.generation_batch_chars,
        "created_for_assets": list(asset_ids),
    }


def _source_snapshot(db: Session, asset: Asset) -> dict[str, Any]:
    run = current_run(db, asset.id)
    if run is None:
        raise GenerationInputError(
            f"{asset.original_name} 还没有完成的解析版本", code="parse_missing",
        )
    try:
        quality = QualityReport.from_dict(json.loads(run.quality_json or "{}"))
    except (TypeError, ValueError):
        quality = QualityReport()
    if not quality.generation_allowed:
        raise GenerationInputError(
            quality.generation_block_reason or f"{asset.original_name} 解析质量不足，不能生成正文",
            code="parse_quality_insufficient",
        )
    document = load_ir(db, run)
    sections = []
    for section in document.sections:
        blocks = []
        for block in document.section_blocks(section):
            blocks.append(_block_payload(block))
        sections.append({
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "blocks": blocks,
        })
    if not sections:
        # A document without sections still needs a stable grouping.
        blocks = [_block_payload(block) for block in document.all_blocks() if block.searchable_text()]
        sections = [{
            "section_id": "sec-1", "title": asset.original_name, "level": 0,
            "page_start": 1, "page_end": max(1, document.page_count), "blocks": blocks,
        }]
    return {
        "asset_id": asset.id,
        "name": asset.original_name,
        "mime_type": asset.mime_type,
        "doc_type": document.doc_type,
        "page_count": document.page_count,
        "parse_run_id": run.id,
        "ir_fingerprint": run.fingerprint,
        "parser": f"{run.parser_name}@{run.parser_version}",
        "quality": quality.to_dict(),
        "sections": sections,
    }


def _block_payload(block) -> dict[str, Any]:
    table = None
    if block.table:
        table = {
            "rows": [row[:MAX_TABLE_COLS] for row in block.table.rows[:MAX_TABLE_ROWS]],
            "header_rows": block.table.header_rows,
        }
    figure = None
    if block.figure:
        figure = {
            "kind": block.figure.kind,
            "description": (block.figure.description or "")[:MAX_FIGURE_CHARS] or None,
            "nodes": block.figure.nodes[:40],
            "edges": block.figure.edges[:40],
            "latex": block.figure.latex,
            "uncertain": block.figure.uncertain,
        }
    return {
        "block_id": block.block_id,
        "page_number": block.page_number,
        "type": block.type,
        "text": block.text[:MAX_BLOCK_CHARS],
        "latex": block.latex,
        "table": table,
        "figure": figure,
        "confidence": block.confidence,
        "warnings": block.warnings[:5],
    }


def current_outline(content: dict[str, Any]) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for node in content.get("content") or []:
        if not isinstance(node, dict) or node.get("type") != "heading":
            continue
        attrs = node.get("attrs") or {}
        outline.append({
            "block_id": attrs.get("blockId"),
            "level": attrs.get("level") or 1,
            "heading": node_text(node).strip()[:300],
        })
    return outline


def current_section_texts(content: dict[str, Any]) -> dict[str, str]:
    """Normalized heading -> following text, used for duplicate avoidance."""

    result: dict[str, str] = {}
    current: str | None = None
    for node in content.get("content") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "heading":
            current = _normalize(node_text(node))
            result.setdefault(current, "")
        elif current is not None:
            result[current] = f"{result[current]}\n{node_text(node)}".strip()
    return result


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def block_chars(block: dict[str, Any]) -> int:
    total = len(block.get("text") or "")
    table = block.get("table")
    if table:
        total += sum(len(" ".join(row)) for row in table.get("rows") or [])
    figure = block.get("figure")
    if figure:
        total += len(figure.get("description") or "") + len(" ".join(figure.get("nodes") or []))
    return total
