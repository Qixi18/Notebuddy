"""Notebook-derived knowledge projections and proposal review use cases."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeChange, KnowledgeProposal, Notebook, NotebookSection
from app.knowledge.proposals import apply_proposal
from app.services.errors import ApplicationError
from app.services.resource_scopes import require_course


def _sections(db: Session, course_id: str):
    require_course(db, course_id)
    return db.execute(select(NotebookSection, Notebook)
        .join(Notebook, Notebook.id == NotebookSection.notebook_id)
        .where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
        .order_by(Notebook.display_order, NotebookSection.order)).all()


def knowledge_graph(db: Session, course_id: str) -> dict:
    nodes, occurrences = [], []
    for section, notebook in _sections(db, course_id):
        name = section.heading.strip() or f"第 {section.order + 1} 节"
        nodes.append({"id": section.block_id, "course_id": course_id, "name": name,
            "summary": section.text[:300] or None, "status": "derived", "sources": [],
            "notebook_id": notebook.id, "notebook_title": notebook.title,
            "level": section.level, "revision": section.revision})
        occurrences.append({"id": section.block_id, "note_id": section.block_id,
            "knowledge_node_id": section.block_id, "material_id": None,
            "section_key": section.block_id, "section_order": section.order,
            "title": name, "notebook_id": notebook.id, "notebook_title": notebook.title})
    return {"nodes": nodes, "edges": [], "occurrences": occurrences}


def knowledge_structure(db: Session, course_id: str) -> dict:
    notebooks: dict[str, dict] = {}
    for section, notebook in _sections(db, course_id):
        book = notebooks.setdefault(notebook.id, {"notebook_id": notebook.id,
            "title": notebook.title, "revision": notebook.document_revision, "sections": []})
        book["sections"].append({"block_id": section.block_id, "heading": section.heading,
            "level": section.level, "order": section.order, "excerpt": section.text[:300]})
    return {"course_id": course_id, "notebooks": list(notebooks.values())}


def list_knowledge_proposals(db: Session, course_id: str, status: str | None = None):
    require_course(db, course_id)
    query = select(KnowledgeProposal).where(KnowledgeProposal.course_id == course_id)
    if status:
        query = query.where(KnowledgeProposal.status == status)
    return list(db.scalars(query.order_by(KnowledgeProposal.created_at.desc())).all())


def review_knowledge_proposal(db: Session, proposal_id: str, *, decision: str, note: str | None):
    proposal = db.get(KnowledgeProposal, proposal_id)
    if proposal is None:
        raise ApplicationError(404, "知识整合提案不存在")
    require_course(db, proposal.course_id)
    try:
        apply_proposal(db, proposal, decision=decision, note=note)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise ApplicationError(422, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(proposal)
    return proposal


def list_knowledge_changes(db: Session, course_id: str) -> list[dict]:
    require_course(db, course_id)
    changes = db.scalars(select(KnowledgeChange).where(
        KnowledgeChange.course_id == course_id
    ).order_by(KnowledgeChange.created_at.desc())).all()
    return [{"id": item.id, "proposal_id": item.proposal_id, "node_id": item.node_id,
        "change_type": item.change_type, "before_json": item.before_json,
        "after_json": item.after_json, "reason": item.reason,
        "created_at": item.created_at} for item in changes]
