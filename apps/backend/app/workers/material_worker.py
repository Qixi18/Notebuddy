from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import (
    KnowledgeNode,
    MaterialPage,
    PageBlock,
    ProcessingJob,
    SourceRef,
    WebSource,
)
from app.knowledge.extractor import extract_material_knowledge
from app.knowledge.proposals import create_note_suggestion
from app.parsers.document import parse_document
from app.parsers.ocr import ocr_pdf_page
from app.retrieval.service import index_material
from app.services.provider_audit import begin_call, finish_call, provider_status_from_error
from app.services.sources import mark_pages_stale
from app.web_search.tavily import WebSearchError
from app.web_search.tavily import configured as web_search_configured
from app.web_search.tavily import search as web_search


def process_material(job_id: str) -> None:
    db = SessionLocal()
    job = None
    try:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status != "processing":
            return
        material = job.material
        job.status = "processing"
        job.phase = "parse"
        job.web_search_status = "waiting" if web_search_configured() else "unavailable"
        job.progress = 5
        job.heartbeat_at = datetime.now(UTC)
        material.status = "processing"
        db.commit()

        source_path = settings.originals_dir / material.stored_filename
        if source_path.suffix.lower() not in settings.allowed_extensions:
            raise ValueError("该资料格式未启用解析器")

        active_pages = [page for page in material.pages if page.is_active]
        if job.kind == "ocr_material":
            if source_path.suffix.lower() != ".pdf":
                raise ValueError("当前只有 PDF 扫描页支持 OCR 任务")
            _run_ocr(db, job, material, source_path)
            should_parse = False
        else:
            should_parse = (
                job.kind == "reparse_material"
                or not active_pages
                or material.page_count != len(active_pages)
            )
        # A retry after knowledge/index failure reuses committed pages. A
        # deliberate reparse creates a new active version and keeps old pages
        # and sources as stale evidence for audit and user review.
        if should_parse:
            parsed_document = replace(
                parse_document(source_path),
                material_id=material.id,
                file_hash=material.content_hash,
            )
            parsed_pages = parsed_document.pages
            if not parsed_pages:
                raise ValueError("资料没有可用的页面或章节")
            if len(parsed_pages) > settings.max_pages:
                raise ValueError(f"资料位置数超过本地限制（最多 {settings.max_pages} 个）")
            mark_pages_stale(db, active_pages)
            for old_page in active_pages:
                old_page.is_active = False
            material.page_count = len(parsed_pages)
            material.parser_version = parsed_document.parser_version
            material.document_warning = "；".join(parsed_document.warnings) or None
            for index, parsed_page in enumerate(parsed_pages, start=1):
                page = MaterialPage(
                    material_id=material.id,
                    page_number=parsed_page.page_number,
                    title=parsed_page.title,
                    raw_text=parsed_page.raw_text,
                    parse_status=parsed_page.parse_status,
                    warning=parsed_page.warning,
                    location_type=parsed_page.location_type,
                    location_label=parsed_page.location_label,
                    stable_location_key=parsed_page.stable_location_key,
                    extraction_method=parsed_page.extraction_method,
                    confidence=parsed_page.confidence,
                    is_active=True,
                )
                db.add(page)
                db.flush()
                for block in parsed_page.blocks:
                    db.add(
                        PageBlock(
                            page_id=page.id,
                            block_type=block.block_type,
                            content=block.content,
                            position=block.position,
                            font_size=block.font_size,
                            is_bold=block.is_bold,
                            object_id=block.object_id,
                            location_label=block.location_label,
                            extraction_method=block.extraction_method,
                            confidence=block.confidence,
                            warning=block.warning,
                        )
                    )
                job.progress = max(5, int(index / max(len(parsed_pages), 1) * 95))
        # The parsed page set becomes visible together; an interruption cannot
        # leave a half-parsed material that the next run mistakes for complete.
        job.heartbeat_at = datetime.now(UTC)
        db.commit()

        job.progress = 96
        job.phase = "knowledge"
        job.heartbeat_at = datetime.now(UTC)
        db.commit()
        extract_material_knowledge(db, material.id)
        if web_search_configured():
            job.phase = "web_search"
            job.heartbeat_at = datetime.now(UTC)
            job.web_search_status = "processing"
            job.progress = 97
            db.commit()
            nodes = list(db.scalars(
                select(KnowledgeNode).distinct()
                .join(KnowledgeNode.source_refs)
                .join(SourceRef.page_block)
                .join(PageBlock.page)
                .where(
                    KnowledgeNode.course_id == material.course_id,
                    MaterialPage.material_id == material.id,
                    MaterialPage.is_active.is_(True),
                    SourceRef.status == "active",
                )
            ).all())
            found = 0
            failed_search_query: str | None = None
            try:
                for node in nodes[:8]:
                    node_sources: list[WebSource] = []
                    search_query = f"{node.name} {material.lecture_title}"
                    failed_search_query = search_query
                    audit, started = begin_call(
                        db,
                        provider="tavily",
                        operation="material_search",
                        course_id=material.course_id,
                        material_id=material.id,
                        model="tavily-basic",
                        request_units=1,
                        metadata={"max_results": 2, "query_length": len(search_query)},
                    )
                    try:
                        search_results = web_search(search_query, max_results=2)
                    except WebSearchError as exc:
                        finish_call(
                            db,
                            audit,
                            started,
                            status=provider_status_from_error(exc),
                            error_type=type(exc).__name__,
                        )
                        raise
                    finish_call(db, audit, started, status="success", response_units=len(search_results))
                    for result in search_results:
                        if result.get("score") is not None and result["score"] < 0.35:
                            continue
                        existing = db.scalar(select(WebSource).where(WebSource.material_id == material.id, WebSource.url == result["url"]))
                        if existing:
                            continue
                        source = WebSource(course_id=material.course_id, material_id=material.id, knowledge_node_id=node.id, search_query=f"{node.name} {material.lecture_title}", **result)
                        db.add(source)
                        db.flush()
                        node_sources.append(source)
                        found += 1
                    if node_sources:
                        for note in node.notes:
                            if note.material_id == material.id:
                                append_web_references(db, note, node_sources)
                job.web_search_status = "completed" if found else "no_results"
                db.commit()
            except WebSearchError as exc:
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                job.web_search_status = "failed"
                job.error_message = f"课件解析已完成；联网检索失败：{exc}"
                if failed_search_query:
                    audit, started = begin_call(
                        db,
                        provider="tavily",
                        operation="material_search",
                        course_id=material.course_id,
                        material_id=material.id,
                        model="tavily-basic",
                        request_units=1,
                        metadata={"query_length": len(failed_search_query), "recovered_after_rollback": True},
                    )
                    finish_call(
                        db,
                        audit,
                        started,
                        status=provider_status_from_error(exc),
                        error_type=type(exc).__name__,
                    )
                db.commit()
        job.phase = "index"
        job.heartbeat_at = datetime.now(UTC)
        job.progress = 98
        db.commit()
        index_material(db, material.id)
        material.status = "completed"
        job.status = "completed"
        job.phase = "completed"
        job.progress = 100
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        if job is None:
            job = db.get(ProcessingJob, job_id)
        if job is not None:
            job.status = "failed"
            job.phase = "failed"
            job.error_message = str(exc)
            job.error_code = "processing_failed"
            job.finished_at = datetime.now(UTC)
            job.progress = 0
            if job.material is not None:
                # An OCR failure must leave the already parsed material
                # browseable; the OCR job itself carries the actionable error.
                job.material.status = (
                    "completed" if job.kind == "ocr_material" and job.material.page_count else "failed"
                )
            if job.kind == "ocr_material":
                job.error_code = "ocr_failed"
            db.commit()
    finally:
        db.close()


def _run_ocr(db, job: ProcessingJob, material, source_path) -> None:
    job.phase = "ocr"
    job.progress = 5
    job.heartbeat_at = datetime.now(UTC)
    db.commit()
    pages = list(db.scalars(
        select(MaterialPage)
        .where(
            MaterialPage.material_id == material.id,
            MaterialPage.is_active.is_(True),
            MaterialPage.parse_status == "ocr_candidate",
        )
        .options(selectinload(MaterialPage.blocks))
        .order_by(MaterialPage.page_number)
    ).all())
    if not pages:
        raise ValueError("当前资料没有待 OCR 的位置")

    for index, page in enumerate(pages, start=1):
        mark_pages_stale(db, [page])
        text, method, confidence = ocr_pdf_page(
            source_path, page_number=page.page_number
        )
        if text:
            page.raw_text = text
            page.title = text.splitlines()[0][:500]
            page.parse_status = "parsed"
            page.warning = "OCR 识别结果；请人工核对原始页面"
            page.extraction_method = method
            page.confidence = confidence
            text_block = next((block for block in page.blocks if not block.content.strip()), None)
            if text_block is None:
                text_block = PageBlock(
                    page_id=page.id,
                    block_type="text",
                    content=text,
                    position=0,
                    object_id=f"ocr-page-{page.page_number}",
                    location_label=page.location_label,
                )
                db.add(text_block)
            else:
                text_block.content = text
                text_block.extraction_method = method
                text_block.confidence = confidence
                text_block.warning = "OCR 识别结果；请人工核对原始页面"
        else:
            page.warning = "OCR 未识别到文字；当前仍没有可引用的原文"
            page.extraction_method = method
            page.confidence = confidence
        job.progress = max(5, int(index / len(pages) * 95))
        job.heartbeat_at = datetime.now(UTC)
    material.parser_version = f"{material.parser_version or 'phase2-1'}+ocr"
    remaining = db.scalar(select(MaterialPage.id).where(
        MaterialPage.material_id == material.id,
        MaterialPage.is_active.is_(True),
        MaterialPage.parse_status == "ocr_candidate",
    ).limit(1))
    if remaining is None:
        material.document_warning = None
    db.commit()


def append_web_references(db, note, sources: list[WebSource]) -> None:
    additions = [source for source in sources if source.url not in note.content_markdown]
    if not additions:
        return
    references = []
    for source in additions:
        safe_title = source.title.replace("]", "\\]")
        snippet = source.snippet[:400].replace("\n", " ")
        references.append(f"- [{safe_title}]({source.url}) · {source.site_name} · 检索于 {source.retrieved_at:%Y-%m-%d}\n  > {snippet}")
    section = "\n\n## 网络拓展阅读（外部来源）\n" + "\n\n".join(references)
    proposed_markdown = note.content_markdown.rstrip() + section
    create_note_suggestion(
        db,
        note_id=note.id,
        proposed_markdown=proposed_markdown,
        source_ids=[],
        impact=(
            f"联网检索为“{note.title}”找到 {len(additions)} 条补充来源；"
            "正文保持不变，请核对来源后决定是否接受。"
        ),
    )
