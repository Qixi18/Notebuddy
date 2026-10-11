"""Reviewable knowledge and note proposal transactions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    KnowledgeChange,
    KnowledgeNode,
    KnowledgeProposal,
    NoteSuggestion,
    SourceRef,
)
from app.knowledge.relations import add_relation


def create_knowledge_proposal(
    db: Session,
    *,
    course_id: str,
    material_id: str | None,
    candidate_name: str,
    candidate_summary: str,
    kind: str,
    confidence: float,
    rationale: str,
    source_ids: list[str] | None = None,
    source_node_id: str | None = None,
    target_node_id: str | None = None,
    status: str = "pending",
    proposed_delta: dict | None = None,
    model_version: str | None = "phase3-rule-1",
) -> KnowledgeProposal:
    filters = [
        KnowledgeProposal.course_id == course_id,
        KnowledgeProposal.candidate_name == candidate_name[:300],
        KnowledgeProposal.kind == kind,
        KnowledgeProposal.status.in_(["pending", "auto_applied"]),
    ]
    filters.append(
        KnowledgeProposal.material_id.is_(None)
        if material_id is None
        else KnowledgeProposal.material_id == material_id
    )
    existing = db.scalar(select(KnowledgeProposal).where(*filters))
    if existing is not None:
        return existing
    proposal = KnowledgeProposal(
        course_id=course_id,
        material_id=material_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        kind=kind,
        candidate_name=candidate_name[:300],
        candidate_summary=candidate_summary,
        confidence=max(0.0, min(1.0, confidence)),
        rationale=rationale,
        source_ids_json=json.dumps(source_ids or [], ensure_ascii=False),
        proposed_delta_json=json.dumps(proposed_delta or {}, ensure_ascii=False),
        status=status,
        model_version=model_version,
    )
    db.add(proposal)
    db.flush()
    return proposal


def _record_change(
    db: Session, proposal: KnowledgeProposal, *, node_id: str | None, change_type: str,
    before: dict, after: dict, reason: str,
) -> KnowledgeChange:
    change = KnowledgeChange(
        course_id=proposal.course_id,
        proposal_id=proposal.id,
        node_id=node_id,
        change_type=change_type,
        before_json=json.dumps(before, ensure_ascii=False),
        after_json=json.dumps(after, ensure_ascii=False),
        reason=reason,
    )
    db.add(change)
    return change


def apply_proposal(db: Session, proposal: KnowledgeProposal, *, decision: str, note: str | None = None) -> KnowledgeProposal:
    if proposal.status not in {"pending", "auto_applied"}:
        return proposal
    if decision not in {"confirm", "reject"}:
        raise ValueError("proposal decision must be confirm or reject")
    proposal.status = "confirmed" if decision == "confirm" else "rejected"
    proposal.review_note = note
    proposal.reviewed_at = datetime.now(UTC)
    if decision == "reject":
        db.flush()
        return proposal

    if proposal.kind == "relation_pending":
        target = db.scalar(select(KnowledgeNode).where(
            KnowledgeNode.course_id == proposal.course_id,
            KnowledgeNode.name == proposal.candidate_name,
        ))
        delta = json.loads(proposal.proposed_delta_json or "{}")
        if target is not None and proposal.source_node_id:
            add_relation(
                db,
                course_id=proposal.course_id,
                source_node_id=proposal.source_node_id,
                target_node_id=target.id,
                relation_type=str(delta.get("relation_type") or "related"),
                confidence=proposal.confidence,
                created_by="reviewed",
            )
        _record_change(
            db, proposal, node_id=proposal.source_node_id, change_type="relation_reviewed",
            before={}, after={"target": target.id if target else None, "relation_type": delta.get("relation_type")},
            reason=proposal.rationale,
        )
        db.flush()
        return proposal

    target = db.get(KnowledgeNode, proposal.target_node_id) if proposal.target_node_id else None
    if proposal.kind == "deepen" and proposal.source_node_id and target is not None:
        # Reviewing similarity links the concepts; each lecture body stays independent.
        add_relation(db, course_id=proposal.course_id, source_node_id=proposal.source_node_id,
                     target_node_id=target.id, relation_type="deepens",
                     confidence=proposal.confidence, created_by="reviewed")
        _record_change(db, proposal, node_id=proposal.source_node_id, change_type="relation_reviewed",
                       before={}, after={"target": target.id, "relation_type": "deepens"},
                       reason=proposal.rationale)
        db.flush()
        return proposal
    if target is None and proposal.kind in {"new", "deepen", "repeat"}:
        target = KnowledgeNode(
            course_id=proposal.course_id,
            name=proposal.candidate_name,
            summary=proposal.candidate_summary,
        )
        db.add(target)
        db.flush()
        proposal.target_node_id = target.id
        change_type = "created"
        before, after = {}, {"name": target.name, "summary": target.summary}
    elif target is not None:
        before = {"name": target.name, "summary": target.summary}
        if proposal.candidate_summary and proposal.kind == "deepen":
            target.summary = proposal.candidate_summary
        after = {"name": target.name, "summary": target.summary}
        change_type = "deepened" if before != after else "source_added"
    else:
        db.flush()
        return proposal

    for source_id in json.loads(proposal.source_ids_json or "[]"):
        source = db.get(SourceRef, source_id)
        if source is not None and source not in target.source_refs:
            target.source_refs.append(source)
    _record_change(
        db, proposal, node_id=target.id, change_type=change_type,
        before=before, after=after, reason=proposal.rationale,
    )
    db.flush()
    return proposal


def create_note_suggestion(
    db: Session, *, note_id: str, proposed_markdown: str, source_ids: list[str], impact: str,
) -> NoteSuggestion:
    existing = db.scalar(select(NoteSuggestion).where(
        NoteSuggestion.note_id == note_id,
        NoteSuggestion.status == "pending",
        NoteSuggestion.proposed_markdown == proposed_markdown,
    ))
    if existing is not None:
        return existing
    suggestion = NoteSuggestion(
        note_id=note_id,
        proposed_markdown=proposed_markdown,
        source_ids_json=json.dumps(source_ids, ensure_ascii=False),
        impact=impact,
        status="pending",
    )
    db.add(suggestion)
    db.flush()
    return suggestion
