from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.orchestrator import run_answer, source_payload
from app.api.v1.shared import ensure_course
from app.db.database import get_db
from app.db.models import Material
from app.schemas.api import AssistantClaim, AssistantRequest, AssistantResponse, AssistantSource

router = APIRouter()


def _scope(db: Session, course_id: str, material_id: str | None) -> Material | None:
    ensure_course(db, course_id)
    selected_material = db.get(Material, material_id) if material_id else None
    if material_id and selected_material is None:
        raise HTTPException(status_code=404, detail="所选资料不存在")
    if selected_material and selected_material.course_id != course_id:
        raise HTTPException(status_code=400, detail="所选资料不属于当前课程")
    if selected_material and selected_material.deleted_at is not None:
        raise HTTPException(status_code=404, detail="所选资料不存在")
    return selected_material


@router.post("/courses/{course_id}/assistant", response_model=AssistantResponse)
def ask_assistant(
    course_id: str,
    payload: AssistantRequest,
    db: Session = Depends(get_db),
) -> AssistantResponse:
    _scope(db, course_id, payload.material_id)
    course = ensure_course(db, course_id)
    result = run_answer(
        db,
        course_id=course_id,
        course_name=course.name,
        question=payload.question,
        material_id=payload.material_id,
        page_number=payload.page_number,
        allow_web=payload.allow_web,
        learning_goal=payload.learning_goal,
        teacher_persona=payload.teacher_persona,
    )
    sources = [AssistantSource(**source_payload(chunk)) for chunk in result["chunks"]]
    sources.extend(
        AssistantSource(
            source_type="web", title=item["title"], url=item["url"], site_name=item["site_name"],
            snippet=item["snippet"], published_at=item.get("published_at"),
            support_level="web_supplement",
        ) for item in result["web_results"]
    )
    claims = []
    for claim in result.get("claims", []):
        source_indexes = list(claim.get("chunk_indexes", []))
        source_indexes.extend(len(result["chunks"]) + index for index in claim.get("web_indexes", []))
        has_chunks = bool(claim.get("chunk_indexes"))
        has_web = bool(claim.get("web_indexes"))
        claims.append(AssistantClaim(
            claim_key=str(claim.get("claim_key") or "answer"),
            evidence_type=str(claim.get("evidence_type") or (
                "mixed" if has_chunks and has_web else "web_supplement" if has_web else "course_related"
            )),
            support_level=str(claim.get("support_level") or "related"),
            source_indexes=source_indexes,
        ))
    db.commit()
    return AssistantResponse(
        answer=result["answer"], sources=sources, mode=result["mode"],
        claims=claims, web_search_status=result["web_search_status"],
    )
