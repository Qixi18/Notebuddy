"""Two-path retrieval over Document IR and Notebook body.

- Source-material path: current ParseRun -> DocumentChunk.
- Notebook path: derived NotebookSection (rebuilt on every body save).

Both paths resolve course ownership through ``Notebook.course_id``; neither
uses ``RetrievalChunk.course_id`` or ``Material.course_id``.  Results carry the
parse run / body revision and block ids so an answer can cite traceable evidence.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    DocumentChunk,
    DocumentParseRun,
    Material,
    Notebook,
    NotebookAsset,
    NotebookSection,
)
from app.retrieval.embedding import EmbeddingClient, EmbeddingError
from app.services.provider_audit import begin_call, finish_call, provider_status_from_error


@dataclass(frozen=True)
class RetrievedChunk:
    material_id: str | None
    lecture_title: str
    page_number: int
    text: str
    score: float
    page_block_id: str | None = None
    source_ref_id: str | None = None
    location_label: str | None = None
    score_source: str = "keyword"
    direct_support: bool = True
    kind: str = "document"
    notebook_id: str | None = None
    document_block_id: str | None = None
    parse_run_id: str | None = None
    block_id: str | None = None
    notebook_revision: int | None = None
    asset_id: str | None = None
    page_numbers: tuple[int, ...] = ()
    document_block_ids: tuple[str, ...] = ()


def retrieve(
    db: Session,
    *,
    course_id: str,
    question: str,
    material_id: str | None = None,
    page_number: int | None = None,
    limit: int = 5,
    notebook_id: str | None = None,
) -> list[RetrievedChunk]:
    terms = query_terms(question)
    query_vector = _embed_query(db, course_id, question)
    documents = [] if notebook_id else _retrieve_documents(
        db, course_id=course_id, terms=terms, query_vector=query_vector,
        material_id=material_id, page_number=page_number,
    )
    # A material-scoped question means exactly that source asset. Do not silently
    # mix unrelated Notebook body chunks into the result set.
    notebooks = [] if material_id else _retrieve_notebooks(
        db, course_id=course_id, terms=terms, query_vector=query_vector,
        notebook_id=notebook_id,
    )
    merged = sorted(documents + notebooks, key=lambda item: item.score, reverse=True)
    return merged[:limit]


def _embed_query(db: Session, course_id: str, question: str) -> list[float] | None:
    client = EmbeddingClient()
    if not client.configured:
        return None
    audit, started = begin_call(
        db, provider="embedding", operation="embed_query", course_id=course_id,
        model=client.settings.embedding_model, request_units=1,
    )
    try:
        vector = client.embed([question])[0]
    except EmbeddingError as exc:
        finish_call(db, audit, started, status=provider_status_from_error(exc),
                    error_type=type(exc).__name__)
        return None
    finish_call(db, audit, started, status="success", response_units=1)
    return vector


def _retrieve_documents(
    db: Session,
    *,
    course_id: str,
    terms: list[str],
    query_vector: list[float] | None,
    material_id: str | None,
    page_number: int | None,
) -> list[RetrievedChunk]:
    query = (
        select(DocumentChunk, Asset, Notebook, Material)
        .join(DocumentParseRun, DocumentParseRun.id == DocumentChunk.parse_run_id)
        .join(Asset, Asset.id == DocumentParseRun.asset_id)
        .join(NotebookAsset, and_(
            NotebookAsset.asset_id == Asset.id,
            NotebookAsset.is_owner.is_(True),
            NotebookAsset.detached_at.is_(None),
        ))
        .join(Notebook, Notebook.id == NotebookAsset.notebook_id)
        .outerjoin(Material, Material.asset_id == Asset.id)
        .where(
            Notebook.course_id == course_id,
            Notebook.deleted_at.is_(None),
            DocumentParseRun.is_current.is_(True),
            DocumentParseRun.status == "completed",
        )
    )
    if material_id:
        material = db.get(Material, material_id)
        asset_id = material.asset_id if material is not None else material_id
        query = query.where(or_(Material.id == material_id, Asset.id == asset_id))
    rows = db.execute(query).all()
    results: list[RetrievedChunk] = []
    for chunk, asset, notebook, material in rows:
        page_numbers = _json_list(chunk.page_numbers_json)
        if page_number and page_number not in page_numbers:
            continue
        lexical = _lexical_score(chunk.text, terms)
        vector = 0.0
        if query_vector and chunk.embedding_json and chunk.embedding_model == settings_model():
            try:
                stored = json.loads(chunk.embedding_json)
                if (isinstance(stored, list) and len(stored) == len(query_vector)
                        and all(isinstance(value, (int, float)) and math.isfinite(value)
                                for value in stored)):
                    vector = cosine_similarity(query_vector, stored)
            except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
                vector = 0.0
        score = vector * 10 + lexical
        if score <= 0:
            continue
        body_block_ids = [str(value) for value in _json_list(chunk.block_ids_json) if value]
        stable_pages = tuple(sorted({int(value) for value in page_numbers if str(value).isdigit() and int(value) > 0}))
        stable_blocks = tuple(dict.fromkeys(body_block_ids))
        precise_page = page_number if page_number in stable_pages else stable_pages[0] if len(stable_pages) == 1 else 0
        precise_block = stable_blocks[0] if len(stable_blocks) == 1 else None
        results.append(RetrievedChunk(
            material_id=material.id if material is not None else None,
            lecture_title=asset.original_name,
            page_number=precise_page,
            text=chunk.text,
            score=score,
            page_block_id=None,
            source_ref_id=None,
            location_label=(f"第 {precise_page} 页" if precise_page else "跨页片段" if len(stable_pages) > 1 else None),
            score_source="hybrid" if vector else "keyword",
            direct_support=lexical > 0 or vector >= 0.55,
            kind="document",
            notebook_id=notebook.id,
            document_block_id=precise_block,
            parse_run_id=chunk.parse_run_id,
            asset_id=asset.id,
            page_numbers=stable_pages,
            document_block_ids=stable_blocks,
        ))
    return results


def _retrieve_notebooks(
    db: Session, *, course_id: str, terms: list[str], query_vector: list[float] | None,
    notebook_id: str | None = None,
) -> list[RetrievedChunk]:
    rows = db.execute(
        select(NotebookSection, Notebook)
        .join(Notebook, Notebook.id == NotebookSection.notebook_id)
        .where(
            Notebook.course_id == course_id,
            Notebook.deleted_at.is_(None),
            *([Notebook.id == notebook_id] if notebook_id else []),
        )
    ).all()
    results: list[RetrievedChunk] = []
    for section, notebook in rows:
        heading_score = 3.0 * _lexical_score(section.heading, terms)
        body_score = _lexical_score(section.text, terms)
        score = heading_score + body_score
        if score <= 0:
            continue
        results.append(RetrievedChunk(
            material_id=None,
            lecture_title=notebook.title,
            page_number=0,
            text=(f"{section.heading}\n{section.text}" if section.heading else section.text)[:4_000],
            score=score,
            location_label=f"第 {section.order + 1} 节",
            score_source="keyword",
            direct_support=True,
            kind="notebook",
            notebook_id=notebook.id,
            block_id=section.block_id,
            notebook_revision=section.revision,
        ))
    return results


def _lexical_score(text: str, terms: list[str]) -> float:
    haystack = (text or "").lower()
    if not haystack:
        return 0.0
    return float(sum(haystack.count(term) for term in terms))


def _json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def build_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for chunk in chunks:
        if chunk.kind == "notebook":
            header = f"[课程笔记：{chunk.lecture_title} | {chunk.location_label or '当前正文'}]"
        else:
            location = chunk.location_label or (f"第 {chunk.page_number} 页" if chunk.page_number else "页码未确认")
            header = f"[课程资料：{chunk.lecture_title} | {location}]"
        blocks.append(f"{header}\n{chunk.text}")
    return "\n\n".join(blocks)


def settings_model() -> str:
    from app.core.config import settings

    return settings.embedding_model or "configured-embedding"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return product / (left_norm * right_norm)


def query_terms(question: str) -> list[str]:
    """Extract searchable terms without treating a whole Chinese sentence as one word."""
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", question.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
            if len(token) > 1:
                terms.append(token)
        elif len(token) > 1:
            terms.append(token)
    return list(dict.fromkeys(terms))
