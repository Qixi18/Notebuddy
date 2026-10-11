from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.ai.prompts import build_note_extraction_messages
from app.db.models import (
    KnowledgeNode,
    Material,
    MaterialPage,
    Note,
    NoteRevision,
    NoteSourceMapping,
    PageBlock,
    SourceRef,
)
from app.knowledge.matcher import find_candidates, normalize_name
from app.knowledge.proposals import create_knowledge_proposal, create_note_suggestion
from app.knowledge.relations import add_relation
from app.notes.renderer import render_note_markdown
from app.services.provider_audit import (
    begin_call,
    estimate_token_cost,
    finish_call,
    provider_status_from_error,
)

ALLOWED_RELATIONS = {"related", "prerequisite", "deepens"}


def find_node_by_name(db: Session, course_id: str, name: str) -> KnowledgeNode | None:
    """Compatibility lookup using the same normalization as candidate matching."""
    normalized = normalize_name(name)
    if not normalized:
        return None
    return next((node for node in db.scalars(select(KnowledgeNode).where(
        KnowledgeNode.course_id == course_id
    )).all() if normalize_name(node.name) == normalized), None)


def find_or_create_node(db: Session, course_id: str, name: str, summary: str = "") -> KnowledgeNode:
    node = find_node_by_name(db, course_id, name)
    if node is None:
        node = KnowledgeNode(course_id=course_id, name=clean_title(name), summary=summary)
        db.add(node)
        db.flush()
    return node


def extract_material_knowledge(db: Session, material_id: str) -> list[KnowledgeNode]:
    material = db.scalar(
        select(Material)
        .where(Material.id == material_id)
    )
    if material is None:
        return []

    pages = list(db.scalars(
        select(MaterialPage)
        .where(MaterialPage.material_id == material_id, MaterialPage.is_active.is_(True))
        .options(selectinload(MaterialPage.blocks))
        .order_by(MaterialPage.page_number, MaterialPage.id)
    ).all())

    created_or_updated: list[KnowledgeNode] = []
    relation_queue: list[tuple[KnowledgeNode, object]] = []
    for page in pages:
        if not page.raw_text.strip():
            continue

        source_refs = ensure_source_refs(db, page.blocks, parser_version=material.parser_version)
        draft = extract_page_draft(
            page.title or f"第 {page.page_number} 页",
            page.raw_text,
            db=db,
            course_id=material.course_id,
            material_id=material.id,
        )
        title = clean_title(str(draft.get("title") or page.title or f"第 {page.page_number} 页"))
        summary = str(draft.get("summary") or "").strip()
        candidates = find_candidates(db, course_id=material.course_id, name=title, summary=summary)
        best = candidates[0] if candidates else None
        exact_candidate = bool(best and normalize_name(best.node.name) == normalize_name(title))
        similar_candidate = bool(best and best.score >= 0.72 and not exact_candidate)
        node = best.node if exact_candidate else find_or_create_node(db, material.course_id, title, summary)
        if similar_candidate:
            create_knowledge_proposal(
                db,
                course_id=material.course_id,
                material_id=material.id,
                candidate_name=title,
                candidate_summary=summary,
                kind="deepen",
                confidence=best.score,
                rationale=f"候选知识点“{best.node.name}”与新页面相似；名称不同，不自动合并。",
                source_ids=[source.id for source in source_refs],
                target_node_id=best.node.id,
                source_node_id=node.id,
                proposed_delta={"summary": summary, "page_number": page.page_number},
            )

        node.summary = summary or node.summary
        add_unique_sources(node.source_refs, source_refs)
        note_content = render_note_markdown(
            title=title,
            summary=str(draft.get("summary") or "").strip(),
            key_points=as_text_list(draft.get("key_points")),
            methods=as_text_list(draft.get("methods")),
            formulas=as_text_list(draft.get("formulas")),
            source_refs=source_refs,
        )
        ensure_note(db, material.course_id, node, note_content, source_refs,
                    material_id=material.id,
                    section_key=page.stable_location_key or f"page:{page.page_number}",
                    section_order=page.page_number)
        create_knowledge_proposal(
            db,
            course_id=material.course_id,
            material_id=material.id,
            candidate_name=title,
            candidate_summary=summary,
            kind="repeat" if exact_candidate else "new",
            confidence=1.0 if exact_candidate else 0.0,
            rationale="名称规范化后一致，已自动补充来源。" if exact_candidate else "课程中没有达到合并阈值的相似知识点，已创建候选。",
            source_ids=[source.id for source in source_refs],
            target_node_id=node.id,
            status="auto_applied",
            proposed_delta={"summary": summary},
        )
        relation_queue.append((node, draft.get("relations")))
        created_or_updated.append(node)

    # Resolve all nodes in this material first, then create edges or pending
    # relation proposals so a page order cannot silently drop a valid edge.
    for node, raw_relations in relation_queue:
        ensure_relations(db, material.course_id, node, raw_relations)
    return created_or_updated


def ensure_source_refs(
    db: Session, blocks: Iterable[PageBlock], *, parser_version: str | None = None
) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for block in blocks:
        if not block.content.strip():
            continue
        source_ref = db.scalar(
            select(SourceRef).where(
                SourceRef.page_block_id == block.id,
                SourceRef.source_type == "course_material",
                SourceRef.status == "active",
            )
        )
        if source_ref is None:
            source_ref = SourceRef(
                page_block_id=block.id,
                source_type="course_material",
                quote=block.content[:1000],
                target_label=block.location_label or block.page.location_label,
                parser_version=parser_version,
            )
            db.add(source_ref)
            db.flush()
        refs.append(source_ref)
    return refs


def extract_page_draft(
    title: str,
    text: str,
    *,
    db: Session | None = None,
    course_id: str | None = None,
    material_id: str | None = None,
) -> dict[str, Any]:
    client = DeepSeekClient()
    if client.configured:
        audit = None
        started = None
        if db is not None:
            audit, started = begin_call(
                db,
                provider="deepseek",
                operation="extract_page_draft",
                course_id=course_id,
                material_id=material_id,
                model=client.settings.deepseek_model,
                metadata={"input_characters": len(text[:12000])},
            )
        try:
            draft = client.complete_json(
                build_note_extraction_messages(title, text[:12000]), max_tokens=2400
            )
            if audit is not None and started is not None:
                usage = client.last_usage or {}
                finish_call(
                    db,
                    audit,
                    started,
                    status="success",
                    request_units=usage.get("prompt_tokens"),
                    response_units=usage.get("completion_tokens"),
                    estimated_cost_usd=estimate_token_cost(
                        usage,
                        input_rate_per_million=client.settings.deepseek_input_cost_per_million,
                        output_rate_per_million=client.settings.deepseek_output_cost_per_million,
                    ),
                )
            if isinstance(draft, dict):
                return draft
        except DeepSeekError as exc:
            if audit is not None and started is not None:
                finish_call(
                    db,
                    audit,
                    started,
                    status=provider_status_from_error(exc),
                    error_type=type(exc).__name__,
                )
    return fallback_page_draft(title, text)


def fallback_page_draft(title: str, text: str) -> dict[str, Any]:
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    body = lines[1:] if len(lines) > 1 else lines
    return {
        "title": title,
        "summary": body[0][:300] if body else "该页面已被解析，但没有足够文本生成摘要。",
        "key_points": body[:5],
        "methods": [],
        "formulas": [],
        "relations": [],
    }


def ensure_note(
    db: Session,
    course_id: str,
    node: KnowledgeNode,
    content: str,
    source_refs: list[SourceRef],
    *,
    material_id: str | None = None,
    section_key: str | None = None,
    section_order: int = 0,
) -> Note:
    db.flush()
    filters = [Note.course_id == course_id]
    if material_id is None:
        filters.extend([Note.material_id.is_(None), Note.knowledge_node_id == node.id])
    else:
        if not section_key:
            raise ValueError("Lecture notes require a stable section key")
        material = db.get(Material, material_id)
        if material is None or material.course_id != course_id or node.course_id != course_id:
            raise ValueError("Note, concept and material must belong to the same course")
        filters.extend([Note.material_id == material_id, Note.section_key == section_key])
    note = db.scalar(select(Note).where(*filters).order_by(Note.created_at, Note.id))
    if note is None and material_id is not None:
        migrated = db.scalars(select(Note).where(
            Note.course_id == course_id, Note.material_id == material_id,
            Note.knowledge_node_id == node.id, Note.section_order == section_order,
            Note.section_key.like("legacy:%"),
        )).all()
        if len(migrated) == 1:
            note = migrated[0]
            note.section_key = section_key
    if note is None:
        note = Note(
            course_id=course_id,
            knowledge_node_id=node.id,
            material_id=material_id,
            section_key=section_key,
            section_order=section_order,
            title=node.name,
            content_markdown=content,
            content_origin="ai",
            user_locked=False,
            revision_number=1,
        )
        db.add(note)
        db.flush()
        db.add(
            NoteRevision(
                note_id=note.id,
                revision_number=1,
                content_markdown=content,
                content_origin="ai",
                user_locked=False,
            )
        )
    elif note.content_markdown != content:
        create_note_suggestion(
            db,
            note_id=note.id,
            proposed_markdown=content,
            source_ids=[source.id for source in source_refs],
            impact=(
                "重新解析生成了新的 AI 笔记草稿；当前正文保持不变，"
                "请先比较来源和差异，再决定是否接受。"
            ),
        )
    add_unique_sources(note.source_refs, source_refs)
    existing = {
        (mapping.note_id, mapping.source_ref_id, mapping.fragment_key)
        for mapping in db.scalars(
            select(NoteSourceMapping).where(NoteSourceMapping.note_id == note.id)
        ).all()
    }
    for source_ref in source_refs:
        key = (note.id, source_ref.id, "whole-note")
        if key not in existing:
            db.add(NoteSourceMapping(
                note_id=note.id,
                source_ref_id=source_ref.id,
                fragment_key="whole-note",
                citation_type="whole_note",
                status=source_ref.status,
                parser_version=source_ref.parser_version,
            ))
    return note


def ensure_relations(
    db: Session,
    course_id: str,
    node: KnowledgeNode,
    raw_relations: object,
) -> None:
    if not isinstance(raw_relations, list):
        return
    for relation in raw_relations:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation_type") or "").strip()
        target_name = clean_title(str(relation.get("target_name") or ""))
        if relation_type not in ALLOWED_RELATIONS or not target_name or target_name == node.name:
            continue
        target = find_node_by_name(db, course_id, target_name)
        confidence = relation.get("confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None
        if target is None:
            create_knowledge_proposal(
                db,
                course_id=course_id,
                material_id=None,
                source_node_id=node.id,
                candidate_name=target_name,
                candidate_summary="",
                kind="relation_pending",
                confidence=confidence_value or 0.0,
                rationale="关系目标尚未解析，保留为待确认关系。",
                proposed_delta={"relation_type": relation_type},
            )
            continue
        add_relation(
            db,
            course_id=course_id,
            source_node_id=node.id,
            target_node_id=target.id,
            relation_type=relation_type,
            confidence=confidence_value,
            created_by="deepseek" if DeepSeekClient().configured else "fallback",
        )


def add_unique_sources(target: list[SourceRef], incoming: Iterable[SourceRef]) -> None:
    existing_ids = {item.id for item in target}
    for source_ref in incoming:
        if source_ref.id not in existing_ids:
            target.append(source_ref)
            existing_ids.add(source_ref.id)


def as_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def clean_title(value: str) -> str:
    return " ".join(value.strip().split())[:300] or "未命名知识点"
