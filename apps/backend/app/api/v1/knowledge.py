from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import (
    KnowledgeChange,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeProposal,
    Material,
    MaterialPage,
    Note,
    PageBlock,
    SourceRef,
)
from app.knowledge.proposals import apply_proposal
from app.schemas.api import (
    KnowledgeChangeRead,
    KnowledgeEdgeRead,
    KnowledgeGraphRead,
    KnowledgeNodeRead,
    KnowledgeNodeSourceRead,
    KnowledgeNodeWithSourcesRead,
    KnowledgeProposalRead,
    ProposalReview,
)

router = APIRouter()


@router.get("/courses/{course_id}/knowledge-graph", response_model=KnowledgeGraphRead)
def get_knowledge_graph(course_id: str, db: Session = Depends(get_db)) -> KnowledgeGraphRead:
    ensure_course(db, course_id)
    nodes = list(
        db.scalars(
            select(KnowledgeNode).options(
                selectinload(KnowledgeNode.source_refs)
                .selectinload(SourceRef.page_block)
                .selectinload(PageBlock.page)
                .selectinload(MaterialPage.material)
            )
            .where(KnowledgeNode.course_id == course_id)
            .order_by(KnowledgeNode.name)
        ).all()
    )
    edges = list(
        db.scalars(
            select(KnowledgeEdge)
            .where(KnowledgeEdge.course_id == course_id)
            .order_by(KnowledgeEdge.created_at)
        ).all()
    )
    return KnowledgeGraphRead(
        nodes=[
            KnowledgeNodeWithSourcesRead(
                **KnowledgeNodeRead.model_validate(node).model_dump(),
                sources=[
                    KnowledgeNodeSourceRead(
                        material_id=source.page_block.page.material_id,
                        lecture_title=source.page_block.page.material.lecture_title,
                        topic_title=source.page_block.page.material.topic_title,
                        page_number=source.page_block.page.page_number,
                    )
                    for source in node.source_refs
                    if source.status == "active" and source.page_block.page.is_active and source.page_block.page.material.deleted_at is None
                ],
            )
            for node in nodes
        ],
        edges=[KnowledgeEdgeRead.model_validate(edge) for edge in edges],
        occurrences=[{
            "id": note.id, "note_id": note.id, "knowledge_node_id": note.knowledge_node_id,
            "material_id": note.material_id, "section_key": note.section_key,
            "section_order": note.section_order, "title": note.title,
        } for note in db.scalars(select(Note).outerjoin(Material, Note.material_id == Material.id)
                                .where(Note.course_id == course_id, Material.deleted_at.is_(None))
                                .order_by(Material.chapter_order, Note.section_order, Note.id)).all()],
    )


@router.get("/courses/{course_id}/knowledge-proposals", response_model=list[KnowledgeProposalRead])
def list_knowledge_proposals(course_id: str, status: str | None = None, db: Session = Depends(get_db)) -> list[KnowledgeProposal]:
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
