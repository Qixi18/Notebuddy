from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    KnowledgeChange,
    KnowledgeProposal,
    Notebook,
    NotebookSection,
)
from app.knowledge.proposals import apply_proposal
from app.schemas.api import (
    KnowledgeChangeRead,
    KnowledgeProposalRead,
    ProposalReview,
)

router = APIRouter()


@router.get("/courses/{course_id}/knowledge-graph")
def get_knowledge_graph(course_id: str, db: Session = Depends(get_db)) -> dict:
    """Course knowledge structure derived from Notebook body sections.

    ``KnowledgeNode`` is no longer the source of truth; the returned nodes use
    the stable body block id so every item traces back to the editable text.
    """

    ensure_course(db, course_id)
    rows = db.execute(
        select(NotebookSection, Notebook)
        .join(Notebook, Notebook.id == NotebookSection.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
        .order_by(Notebook.display_order, NotebookSection.order)
    ).all()
    nodes = []
    occurrences = []
    for section, notebook in rows:
        name = section.heading.strip() or f"第 {section.order + 1} 节"
        nodes.append({
            "id": section.block_id,
            "course_id": course_id,
            "name": name,
            "summary": section.text[:300] or None,
            "status": "derived",
            "sources": [],
            "notebook_id": notebook.id,
            "notebook_title": notebook.title,
            "level": section.level,
            "revision": section.revision,
        })
        occurrences.append({
            "id": section.block_id,
            "note_id": section.block_id,
            "knowledge_node_id": section.block_id,
            "material_id": None,
            "section_key": section.block_id,
            "section_order": section.order,
            "title": name,
            "notebook_id": notebook.id,
            "notebook_title": notebook.title,
        })
    return {"nodes": nodes, "edges": [], "occurrences": occurrences}


@router.get("/courses/{course_id}/knowledge-structure")
def get_knowledge_structure(course_id: str, db: Session = Depends(get_db)) -> dict:
    ensure_course(db, course_id)
    rows = db.execute(
        select(NotebookSection, Notebook)
        .join(Notebook, Notebook.id == NotebookSection.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
        .order_by(Notebook.display_order, NotebookSection.order)
    ).all()
    notebooks: dict[str, dict] = {}
    for section, notebook in rows:
        book = notebooks.setdefault(notebook.id, {
            "notebook_id": notebook.id,
            "title": notebook.title,
            "revision": notebook.document_revision,
            "sections": [],
        })
        book["sections"].append({
            "block_id": section.block_id,
            "heading": section.heading,
            "level": section.level,
            "order": section.order,
            "excerpt": section.text[:300],
        })
    return {"course_id": course_id, "notebooks": list(notebooks.values())}


@router.get("/courses/{course_id}/knowledge-proposals", response_model=list[KnowledgeProposalRead])
def list_knowledge_proposals(course_id: str, status: str | None = None,
                             db: Session = Depends(get_db)) -> list[KnowledgeProposal]:
    ensure_course(db, course_id)
    query = select(KnowledgeProposal).where(KnowledgeProposal.course_id == course_id)
    if status:
        query = query.where(KnowledgeProposal.status == status)
    return list(db.scalars(query.order_by(KnowledgeProposal.created_at.desc())).all())


@router.post("/knowledge-proposals/{proposal_id}/review", response_model=KnowledgeProposalRead)
def review_knowledge_proposal(
    proposal_id: str, payload: ProposalReview, db: Session = Depends(get_db)
) -> KnowledgeProposal:
    proposal = db.get(KnowledgeProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="知识整合提案不存在")
    ensure_course(db, proposal.course_id)
    apply_proposal(db, proposal, decision=payload.decision, note=payload.note)
    db.commit()
    db.refresh(proposal)
    return proposal


@router.get("/courses/{course_id}/knowledge-changes", response_model=list[KnowledgeChangeRead])
def list_knowledge_changes(course_id: str, db: Session = Depends(get_db)) -> list[dict]:
    ensure_course(db, course_id)
    changes = list(db.scalars(
        select(KnowledgeChange).where(KnowledgeChange.course_id == course_id)
        .order_by(KnowledgeChange.created_at.desc())
    ).all())
    return [
        {
            "id": item.id,
            "proposal_id": item.proposal_id,
            "node_id": item.node_id,
            "change_type": item.change_type,
            "before_json": item.before_json,
            "after_json": item.after_json,
            "reason": item.reason,
            "created_at": item.created_at,
        }
        for item in changes
    ]
