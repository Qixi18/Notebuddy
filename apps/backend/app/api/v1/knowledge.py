from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.api import KnowledgeChangeRead, KnowledgeProposalRead, ProposalReview
from app.services.knowledge_reads import (
    knowledge_graph,
    knowledge_structure,
    list_knowledge_changes,
    review_knowledge_proposal,
)
from app.services.knowledge_reads import (
    list_knowledge_proposals as read_knowledge_proposals,
)

router = APIRouter()


@router.get("/courses/{course_id}/knowledge-graph")
def get_knowledge_graph(course_id: str, db: Session = Depends(get_db)) -> dict:
    return knowledge_graph(db, course_id)


@router.get("/courses/{course_id}/knowledge-structure")
def get_knowledge_structure(course_id: str, db: Session = Depends(get_db)) -> dict:
    return knowledge_structure(db, course_id)


@router.get("/courses/{course_id}/knowledge-proposals", response_model=list[KnowledgeProposalRead])
def list_knowledge_proposals(course_id: str, status: str | None = None,
                             db: Session = Depends(get_db)):
    return read_knowledge_proposals(db, course_id, status)


@router.post("/knowledge-proposals/{proposal_id}/review", response_model=KnowledgeProposalRead)
def review_proposal(proposal_id: str, payload: ProposalReview,
                    db: Session = Depends(get_db)):
    return review_knowledge_proposal(
        db, proposal_id, decision=payload.decision, note=payload.note,
    )


@router.get("/courses/{course_id}/knowledge-changes", response_model=list[KnowledgeChangeRead])
def get_knowledge_changes(course_id: str, db: Session = Depends(get_db)):
    return list_knowledge_changes(db, course_id)
