"""Course-scoped term excerpts shared by HTTP and agent tools."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Material, MaterialPage, PageBlock, RetrievalChunk
from app.schemas.api import TermExplanationRequest, TermExplanationResponse
from app.schemas.terms import TermExplanationSource


def explain_term_from_course(db: Session, *, course_id: str, payload: TermExplanationRequest) -> TermExplanationResponse:
    term = payload.term.strip()
    matches = list(db.execute(
        select(RetrievalChunk, PageBlock, MaterialPage, Material)
        .join(PageBlock, RetrievalChunk.page_block_id == PageBlock.id)
        .join(MaterialPage, PageBlock.page_id == MaterialPage.id)
        .join(Material, MaterialPage.material_id == Material.id)
        .where(
            RetrievalChunk.course_id == course_id,
            Material.deleted_at.is_(None),
            MaterialPage.is_active.is_(True),
            PageBlock.content != "",
            RetrievalChunk.text.ilike(f"%{term}%"),
        )
        .order_by(Material.lecture_title, MaterialPage.page_number, PageBlock.position)
        .limit(3)
    ).all())
    sources = [TermExplanationSource(
        material_id=material.id,
        lecture_title=material.lecture_title,
        page_number=page.page_number,
        location_label=block.location_label or page.location_label,
        snippet=chunk.text[:400],
    ) for chunk, block, page, material in matches]
    if sources:
        locations = "、".join(f"{item.lecture_title}第{item.page_number}页" for item in sources)
        return TermExplanationResponse(
            original=term,
            common_translations=[],
            discipline=payload.discipline,
            explanation=(
                f"课程原文在 {locations} 出现了“{term}”。下面的摘录用于定位课程语境；"
                "它不是未经核验的词源或跨学科定义。"
            ),
            source_note="课程资料直接命中；词源和常见译法仍需可靠术语资料核对。",
            uncertain=False,
            sources=sources,
        )
    return TermExplanationResponse(
        original=term,
        common_translations=[],
        discipline=payload.discipline,
        explanation=(
            "当前未配置可核验的术语解释服务；请把该词放回课程原文中理解，"
            "不要把未有出处的词源或类比当成学术定义。"
        ),
        source_note="通用解释；本地没有匹配到可引用的课程来源。",
        uncertain=True,
        sources=[],
    )
