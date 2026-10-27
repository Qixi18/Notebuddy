"""Display contract for live answers and persisted evidence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ConversationMessage, Material
from app.retrieval.service import RetrievedChunk


def source_payload(chunk: RetrievedChunk) -> dict:
    payload = {
        "source_type": "notebook" if chunk.kind == "notebook" else "course_material",
        "material_id": chunk.material_id,
        "source_ref_id": chunk.source_ref_id,
        "lecture_title": chunk.lecture_title,
        "page_number": chunk.page_number,
        "location_label": chunk.location_label,
        "snippet": chunk.text[:240],
        "support_level": "direct" if chunk.direct_support else "related",
        "score_source": chunk.score_source,
        "notebook_id": chunk.notebook_id,
        "block_id": chunk.block_id,
        "document_block_id": chunk.document_block_id,
        "parse_run_id": chunk.parse_run_id,
        "notebook_revision": chunk.notebook_revision,
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
        })
    return sources


def sources_from_evidence(db: Session, message: ConversationMessage) -> list[dict]:
    """会话消息落库时只保存了 evidence，这里还原成前端可直接渲染的来源卡片。

    与 ``/courses/{id}/assistant`` 返回的 sources 保持同一结构，合并答疑链路后
    悬浮答疑坞与答疑页才能拿到完全一致的来源信息（此前会话链路没有 sources）。
    """
    sources: list[dict] = []
    seen: set[str] = set()
    for item in message.evidence:
        if item.document_block_id or item.notebook_id:
            key = f"new:{item.notebook_id}:{item.body_block_id}:{item.document_block_id}"
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "source_type": "notebook" if not item.document_block_id else "course_material",
                "notebook_id": item.notebook_id,
                "block_id": item.body_block_id,
                "document_block_id": item.document_block_id,
                "parse_run_id": item.parse_run_id,
                "location_label": item.location_label,
                "lecture_title": item.source_title,
                "snippet": item.snippet,
                "support_level": item.support_level,
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
            })
    return sources
