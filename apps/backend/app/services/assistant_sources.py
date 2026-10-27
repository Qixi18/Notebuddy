"""Display contract for live answers and persisted evidence."""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    ConversationMessage,
    DocumentBlock,
    DocumentParseRun,
    Material,
    Notebook,
    NotebookAsset,
    NotebookBlockSource,
    NotebookSection,
)
from app.retrieval.service import RetrievedChunk


def source_payload(chunk: RetrievedChunk) -> dict:
    payload = {
        "source_type": "notebook" if chunk.kind == "notebook" else "course_material",
        "material_id": chunk.material_id,
        "asset_id": chunk.asset_id,
        "source_ref_id": chunk.source_ref_id,
        "lecture_title": chunk.lecture_title,
        "page_number": chunk.page_number or None,
        "page_numbers": list(chunk.page_numbers),
        "document_block_ids": list(chunk.document_block_ids),
        "location_label": chunk.location_label,
        "snippet": chunk.text[:240],
        "support_level": "direct" if chunk.direct_support else "related",
        "score_source": chunk.score_source,
        "notebook_id": chunk.notebook_id,
        "block_id": chunk.block_id,
        "document_block_id": chunk.document_block_id,
        "parse_run_id": chunk.parse_run_id,
        "notebook_revision": chunk.notebook_revision,
        "source_status": "active",
    }
    return payload


def sources_from_results(chunks: list[RetrievedChunk], web_results: list[dict]) -> list[dict]:
    sources = [source_payload(chunk) for chunk in chunks]
    for item in web_results:
        sources.append({
            "source_type": "web",
            "title": item.get("title"),
            "url": item.get("url"),
            "site_name": item.get("site_name"),
            "snippet": item.get("snippet"),
            "published_at": item.get("published_at"),
            "support_level": "supplement",
            "source_status": "active",
        })
    return sources


def _persisted_source_status(db: Session, item, parse_run: DocumentParseRun | None) -> str:
    """Resolve whether a stored citation still points at the current source."""
    if item.parse_run_id:
        if parse_run is None or parse_run.status != "completed":
            return "unavailable"
        asset = db.get(Asset, parse_run.asset_id)
        if asset is None or asset.state != "ready":
            return "unavailable"
        document_block_ids = _json_values(item.document_block_ids_json, item.document_block_id)
        if document_block_ids:
            existing_ids = set(db.scalars(select(DocumentBlock.block_id).where(
                DocumentBlock.parse_run_id == item.parse_run_id,
                DocumentBlock.block_id.in_(document_block_ids),
            )).all())
            if len(existing_ids) != len(set(document_block_ids)):
                return "unavailable"
        material = db.scalar(select(Material).where(Material.asset_id == asset.id))
        if material is not None and material.deleted_at is not None:
            return "unavailable"
        if not parse_run.is_current:
            return "stale"
        if item.notebook_id:
            notebook = db.get(Notebook, item.notebook_id)
            if notebook is None or notebook.deleted_at is not None:
                return "unavailable"
            owner = db.scalar(select(NotebookAsset.id).where(
                NotebookAsset.notebook_id == item.notebook_id,
                NotebookAsset.asset_id == asset.id,
                NotebookAsset.detached_at.is_(None),
            ))
            if owner is None:
                return "unavailable"
            if item.body_block_id:
                edge = db.scalar(select(NotebookBlockSource).where(
                    NotebookBlockSource.notebook_id == item.notebook_id,
                    NotebookBlockSource.block_id == item.body_block_id,
                    NotebookBlockSource.document_block_id.in_(document_block_ids or [item.document_block_id]),
                    NotebookBlockSource.parse_run_id == item.parse_run_id,
                ))
                if edge is not None and edge.status == "stale":
                    return "stale"
        return "active"

    notebook = db.get(Notebook, item.notebook_id) if item.notebook_id else None
    if notebook is None or notebook.deleted_at is not None:
        return "unavailable"
    if item.body_block_id:
        section = db.scalar(select(NotebookSection).where(
            NotebookSection.notebook_id == notebook.id,
            NotebookSection.block_id == item.body_block_id,
        ))
        if section is None:
            return "stale"
        if item.notebook_revision is not None and notebook.document_revision != item.notebook_revision:
            return "stale"
        edges = db.scalars(select(NotebookBlockSource).where(
            NotebookBlockSource.notebook_id == notebook.id,
            NotebookBlockSource.block_id == item.body_block_id,
        )).all()
        if edges and all(edge.status == "stale" for edge in edges):
            return "stale"
    return "active"


def _json_values(raw: str | None, fallback: str | None = None) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        value = []
    values = value if isinstance(value, list) else []
    if not values and fallback:
        values = [fallback]
    return values


def sources_from_evidence(db: Session, message: ConversationMessage) -> list[dict]:
    """会话消息落库时只保存了 evidence，这里还原成前端可直接渲染的来源卡片。

    与 ``/courses/{id}/assistant`` 返回的 sources 保持同一结构，合并答疑链路后
    悬浮答疑坞与答疑页才能拿到完全一致的来源信息（此前会话链路没有 sources）。
    """
    sources: list[dict] = []
    seen: set[str] = set()
    for item in message.evidence:
        if item.parse_run_id or item.document_block_id or item.notebook_id:
            block_ids = _json_values(item.document_block_ids_json, item.document_block_id)
            page_numbers = [int(value) for value in _json_values(item.page_numbers_json)
                            if str(value).isdigit() and int(value) > 0]
            key = f"new:{item.notebook_id}:{item.body_block_id}:{item.parse_run_id}:{','.join(map(str, block_ids))}"
            if key in seen:
                continue
            seen.add(key)
            parse_run = db.get(DocumentParseRun, item.parse_run_id) if item.parse_run_id else None
            asset_id = parse_run.asset_id if parse_run else None
            material = db.scalar(select(Material).where(Material.asset_id == asset_id)) if asset_id else None
            asset = db.get(Asset, asset_id) if asset_id else None
            page_match = re.fullmatch(r"第 (\d+) 页", item.location_label or "")
            if not page_numbers and page_match:
                page_numbers = [int(page_match.group(1))]
            page_number = page_numbers[0] if len(page_numbers) == 1 else None
            sources.append({
                "source_type": "course_material" if item.parse_run_id else "notebook",
                "notebook_id": item.notebook_id,
                "block_id": item.body_block_id,
                "document_block_id": item.document_block_id,
                "document_block_ids": block_ids,
                "parse_run_id": item.parse_run_id,
                "location_label": item.location_label,
                "lecture_title": item.source_title,
                "material_id": material.id if material else None,
                "asset_id": asset.id if asset else asset_id,
                "page_number": page_number,
                "page_numbers": page_numbers,
                "snippet": item.snippet,
                "support_level": item.support_level,
                "source_status": _persisted_source_status(db, item, parse_run),
            })
            continue
        ref = item.source_ref
        if ref is not None and ref.page_block is not None:
            key = f"ref:{ref.id}"
            if key in seen:
                continue
            seen.add(key)
            page = ref.page_block.page
            material = db.get(Material, page.material_id) if page is not None else None
            sources.append({
                "source_type": "course_material",
                "source_ref_id": ref.id,
                "material_id": page.material_id if page is not None else None,
                "lecture_title": material.lecture_title if material is not None else None,
                "page_number": page.page_number if page is not None else None,
                "location_label": ref.page_block.location_label or (page.location_label if page is not None else None),
                "snippet": ref.quote,
                "support_level": item.support_level,
                "source_status": ref.status if ref.status in {"active", "stale"} else "unavailable",
            })
            continue
        web = item.web_source
        if web is not None:
            key = f"web:{web.id}"
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "source_type": "web",
                "title": web.title,
                "url": web.url,
                "site_name": web.site_name,
                "snippet": web.snippet,
                "retrieved_at": web.retrieved_at,
                "published_at": web.published_at,
                "support_level": item.support_level,
                "source_status": "active",
            })
    return sources
