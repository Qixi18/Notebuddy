from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.shared import ensure_course, ensure_material, ensure_note
from app.db.database import get_db
from app.db.models import (
    Note,
    NoteSuggestion,
    PageBlock,
    SourceRef,
    WebSource,
)
from app.knowledge.proposals import create_note_suggestion
from app.notes.service import NoteEditConflict, list_course_notes, update_note_as_user
from app.schemas.api import (
    NoteRead,
    NoteRevisionRead,
    NoteSuggestionRead,
    NoteUpdate,
    ProposalReview,
    SourceRefRead,
    WebSourceRead,
)

router = APIRouter()


def _source_ref_read(source_ref: SourceRef) -> SourceRefRead:
    page = source_ref.page_block.page
    return SourceRefRead(
        id=source_ref.id,
        page_block_id=source_ref.page_block_id,
        source_type=source_ref.source_type,
        quote=source_ref.quote,
        material_id=page.material_id,
        page_number=page.page_number,
        location_type=page.location_type,
        location_label=page.location_label or source_ref.target_label,
        status=source_ref.status,
        target_label=source_ref.target_label,
    )


@router.get("/courses/{course_id}/notes", response_model=list[NoteRead])
def get_course_notes(course_id: str, db: Session = Depends(get_db)) -> list[Note]:
    ensure_course(db, course_id)
    return list_course_notes(db, course_id)



@router.get("/notes/{note_id}", response_model=NoteRead)
def get_note(note_id: str, db: Session = Depends(get_db)) -> Note:
    return ensure_note(db, note_id)



@router.get("/notes/{note_id}/revisions", response_model=list[NoteRevisionRead])
def get_note_revisions(note_id: str, db: Session = Depends(get_db)) -> list[NoteRevisionRead]:
    note = ensure_note(db, note_id)
    return [NoteRevisionRead.model_validate(revision) for revision in note.revisions]



@router.get("/notes/{note_id}/web-sources", response_model=list[WebSourceRead])
def get_note_web_sources(note_id: str, db: Session = Depends(get_db)) -> list[WebSource]:
    note = ensure_note(db, note_id)
    query = select(WebSource).where(WebSource.course_id == note.course_id,
                                    WebSource.knowledge_node_id == note.knowledge_node_id)
    if note.material_id is not None:
        query = query.where(WebSource.material_id == note.material_id)
    else:
        material_ids = {source.page_block.page.material_id for source in note.source_refs}
        query = query.where(WebSource.material_id.in_(material_ids))
    return list(db.scalars(query.order_by(WebSource.retrieved_at.desc())).all())



@router.get("/notes/{note_id}/sources", response_model=list[SourceRefRead])
def get_note_sources(note_id: str, db: Session = Depends(get_db)) -> list[SourceRefRead]:
    note = db.scalar(
        select(Note)
        .where(Note.id == note_id)
        .options(
            selectinload(Note.source_refs)
            .selectinload(SourceRef.page_block)
            .selectinload(PageBlock.page)
        )
    )
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    ensure_course(db, note.course_id)
    return [_source_ref_read(source_ref) for source_ref in note.source_refs]


@router.get("/sources/{source_ref_id}", response_model=SourceRefRead)
def get_source(source_ref_id: str, db: Session = Depends(get_db)) -> SourceRefRead:
    source_ref = db.scalar(
        select(SourceRef)
        .where(SourceRef.id == source_ref_id)
        .options(selectinload(SourceRef.page_block).selectinload(PageBlock.page))
    )
    if source_ref is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    ensure_material(db, source_ref.page_block.page.material_id)
    return _source_ref_read(source_ref)



@router.patch("/notes/{note_id}", response_model=NoteRead)
def update_note(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)) -> Note:
    note = ensure_note(db, note_id)
    try:
        return update_note_as_user(
            db, note, payload.content_markdown, payload.expected_revision_number
        )
    except NoteEditConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/notes/{note_id}/suggestions", response_model=list[NoteSuggestionRead])
def get_note_suggestions(note_id: str, db: Session = Depends(get_db)) -> list[NoteSuggestion]:
    ensure_note(db, note_id)
    return list(db.scalars(
        select(NoteSuggestion).where(NoteSuggestion.note_id == note_id)
        .order_by(NoteSuggestion.created_at.desc())
    ).all())


@router.post("/notes/{note_id}/suggestions", response_model=NoteSuggestionRead, status_code=201)
def create_note_suggestion_endpoint(
    note_id: str, payload: dict, db: Session = Depends(get_db)
) -> NoteSuggestion:
    note = ensure_note(db, note_id)
    markdown = str(payload.get("proposed_markdown") or "").strip()
    if not markdown:
        raise HTTPException(status_code=422, detail="建议内容不能为空")
    suggestion = create_note_suggestion(
        db,
        note_id=note.id,
        proposed_markdown=markdown,
        source_ids=[str(item) for item in payload.get("source_ids", []) if item],
        impact=str(payload.get("impact") or "待用户确认的笔记片段").strip(),
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.post("/notes/{note_id}/suggestions/{suggestion_id}/review", response_model=NoteRead)
def review_note_suggestion(
    note_id: str, suggestion_id: str, payload: ProposalReview, db: Session = Depends(get_db)
) -> Note:
    note = ensure_note(db, note_id)
    suggestion = db.get(NoteSuggestion, suggestion_id)
    if suggestion is None or suggestion.note_id != note.id:
        raise HTTPException(status_code=404, detail="笔记建议不存在")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail="笔记建议已经处理")
    suggestion.status = "accepted" if payload.decision == "confirm" else "rejected"
    suggestion.reviewed_at = datetime.now(UTC)
    suggestion.impact = (suggestion.impact + (f"；{payload.note}" if payload.note else "")).strip("；")
    if payload.decision == "confirm":
        try:
            updated = update_note_as_user(db, note, suggestion.proposed_markdown, note.revision_number)
        except NoteEditConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        updated = note
        db.commit()
    db.refresh(updated)
    return updated
