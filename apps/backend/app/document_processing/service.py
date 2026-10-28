"""Document Processing service: ParseRun lifecycle, persistence and views.

Only this module writes ``document_*`` tables.  Parsers produce an IR; the
service seals it, assesses quality, stores pages/blocks/sections/chunks and
makes the run current without ever deleting older versions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.model_utils import new_id
from app.db.models import (
    Asset,
    DocumentBlock,
    DocumentChunk,
    DocumentPage,
    DocumentParseRun,
    DocumentSection,
)
from app.document_processing.adapters.image import parse_image
from app.document_processing.adapters.mineru import MinerUUnavailable
from app.document_processing.adapters.mineru import parse_document as parse_with_mineru
from app.document_processing.adapters.office import parse_office
from app.document_processing.adapters.pdf import ParseContext, parse_pdf
from app.document_processing.chunking import build_chunks
from app.document_processing.engines import ocr as ocr_engine
from app.document_processing.engines import vision as vision_engine
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    QualityReport,
    SectionIR,
    TableData,
)
from app.document_processing.normalization.markdown import render_markdown
from app.document_processing.quality import EngineState, assess

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".pptx", ".docx"}


class DocumentProcessingError(RuntimeError):
    def __init__(self, message: str, *, code: str = "parse_failed") -> None:
        super().__init__(message)
        self.code = code


class UnsupportedDocument(DocumentProcessingError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="unsupported_format")


@dataclass
class ParseOutcome:
    run: DocumentParseRun
    ir: DocumentIR


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def engine_state(*, probe: bool = True) -> EngineState:
    return EngineState(ocr=ocr_engine.availability(probe=probe),
                       vision=vision_engine.availability())


def create_parse_run(
    db: Session,
    *,
    asset: Asset,
    config: dict[str, Any] | None = None,
    reparse: bool = False,
) -> DocumentParseRun:
    """Create a new pending parse version.  The previous current run is kept."""

    current = db.scalar(select(DocumentParseRun).where(
        DocumentParseRun.asset_id == asset.id,
        DocumentParseRun.is_current.is_(True),
    ))
    if current is not None and not reparse and current.status == "completed":
        # Idempotent: a successful current parse is reused unless a reparse is
        # explicitly requested (retrying a failed run still creates a new one).
        return current
    # The HTTP upload path records installed capabilities without loading OCR
    # models; the isolated worker performs the inference preflight before parse.
    states = engine_state(probe=False)
    config = {
        "ocr": states.ocr.to_dict(),
        "vision": states.vision.to_dict(),
        **(config or {}),
    }
    run = DocumentParseRun(
        id=new_id(),
        asset_id=asset.id,
        document_id=asset.id,
        ir_version=1,
        status="pending",
        parser_name="pending",
        parser_version="0",
        config_version="v1",
        config_json=json.dumps(config, ensure_ascii=False),
        is_current=False,
        fingerprint="0" * 64,
        page_count=0,
        text_chars=0,
        quality_status="failed",
        quality_json=json.dumps({"status": "failed", "generation_allowed": False,
                                 "generation_block_reason": "解析尚未完成"}, ensure_ascii=False),
        supersedes_id=current.id if current is not None else None,
        created_at=_now(),
    )
    db.add(run)
    db.flush()
    return run


def execute_parse_run(
    db: Session,
    run_id: str,
    *,
    source_path: Path | None = None,
    title: str = "",
    ocr_available: bool | None = None,
    vision_available: bool | None = None,
    ocr_recognize: Callable[..., object] | None = None,
    vision_describe: Callable[..., object] | None = None,
) -> ParseOutcome:
    run = db.get(DocumentParseRun, run_id)
    if run is None:
        raise DocumentProcessingError("解析版本不存在", code="parse_run_missing")
    if run.status == "completed":
        raise DocumentProcessingError("已完成的解析版本不可再次执行", code="parse_run_completed")
    asset = db.get(Asset, run.asset_id)
    if asset is None:
        raise DocumentProcessingError("资源不存在", code="asset_missing")

    run.status = "running"
    run.started_at = _now()
    run.error_code = run.error_message = None
    # Model downloads/inference may take minutes. Publish the running state
    # before that work so SQLite's write lock does not block the UI or other jobs.
    db.commit()

    path = source_path or _asset_path(asset)
    extension = (asset.extension or path.suffix).lower()
    parser_choice = (os.getenv("NOTEBOOK_DOCUMENT_PARSER", "native").strip().lower() or "native")
    if parser_choice not in {"native", "mineru"}:
        raise DocumentProcessingError(
            "NOTEBOOK_DOCUMENT_PARSER 仅支持 native 或 mineru",
            code="invalid_parser_config",
        )
    doc_type = (
        "image" if asset.media_type == "image" or extension in IMAGE_EXTENSIONS
        else "pdf" if extension == ".pdf"
        else "pptx" if extension == ".pptx"
        else "docx" if extension == ".docx"
        else "unknown"
    )
    if doc_type == "unknown" and parser_choice == "mineru":
        doc_type = extension.lstrip(".") or "document"
    elif doc_type == "unknown":
        raise UnsupportedDocument(
            f"暂不支持该文件格式（{extension or '无扩展名'}）；本轮完整支持 PDF 与 PNG/JPG 图片"
        )

    states = engine_state()
    ocr_ready = states.ocr.available if ocr_available is None else ocr_available
    vision_ready = states.vision.available if vision_available is None else vision_available
    context = ParseContext(
        asset_id=asset.id,
        parse_run_id=run.id,
        doc_type=doc_type,
        file_sha256=asset.sha256,
        title=title or asset.original_name,
    )
    parse_started = time.perf_counter()

    def render_store(page_number: int, png: bytes) -> str:
        return _store_render(asset.id, run.id, page_number, png)

    def figure_store(page_number: int, image: bytes, suffix: str) -> str:
        return _store_figure(asset.id, run.id, page_number, image, suffix)

    try:
        if parser_choice == "mineru":
            document = parse_with_mineru(path, context)
        elif doc_type == "pdf":
            document = parse_pdf(
                path, context, render_store=render_store,
                ocr_available=ocr_ready, vision_available=vision_ready,
                ocr_recognize=ocr_recognize, vision_describe=vision_describe,
                figure_store=figure_store,
            )
        elif doc_type == "image":
            document = parse_image(
                path, context,
                ocr_available=ocr_ready, vision_available=vision_ready,
                ocr_recognize=ocr_recognize, vision_describe=vision_describe,
            )
        else:
            document = parse_office(path, context)
    except (UnsupportedDocument, DocumentProcessingError):
        raise
    except MinerUUnavailable as exc:
        raise DocumentProcessingError(str(exc), code="parser_unavailable") from exc
    except FileNotFoundError as exc:
        raise DocumentProcessingError("原始文件不存在，无法解析", code="asset_missing") from exc
    except Exception as exc:
        raise DocumentProcessingError(f"解析失败：{type(exc).__name__}: {exc}", code="parse_failed") from exc

    document.quality = assess(
        document,
        engines=EngineState(
            ocr=states.ocr if ocr_available is None else _override(
                states.ocr, available=ocr_ready),
            vision=states.vision if vision_available is None else _override(
                states.vision, available=vision_ready),
        ),
        doc_type=doc_type,
        notes=list(document.warnings),
    )
    document.seal()

    _replace_children(db, run, document)
    _markdown = render_markdown(document)
    run.status = "completed"
    run.doc_type = doc_type
    run.parser_name = document.parser_name
    run.parser_version = document.parser_version
    run.config_version = document.config_version
    run.fingerprint = document.fingerprint
    run.page_count = document.page_count
    run.text_chars = document.quality.text_chars
    run.quality_status = document.quality.status
    run.quality_json = json.dumps(document.quality.to_dict(), ensure_ascii=False)
    run.markdown_text = _markdown
    run.finished_at = _now()
    run.error_code = run.error_message = None
    _promote_current(db, run)
    db.flush()
    try:
        import psutil

        rss_bytes = psutil.Process().memory_info().rss
    except Exception:
        rss_bytes = None
    try:
        source_bytes = path.stat().st_size
    except OSError:
        source_bytes = None
    logger.info(
        "document_parse_finished asset_id=%s parse_run_id=%s size_bytes=%s parser=%s "
        "pages=%s pages_ok=%s pages_failed=%s blocks=%s quality=%s generation_allowed=%s "
        "elapsed_seconds=%.3f rss_bytes=%s",
        asset.id, run.id, source_bytes, run.parser_name, run.page_count,
        document.quality.pages_ok, document.quality.pages_failed,
        sum(len(page.blocks) for page in document.pages), document.quality.status,
        document.quality.generation_allowed, time.perf_counter() - parse_started, rss_bytes,
    )
    return ParseOutcome(run=run, ir=document)


def persist_existing_ir(
    db: Session,
    *,
    asset: Asset,
    document: DocumentIR,
    config: dict[str, Any] | None = None,
) -> ParseOutcome:
    """Persist an IR assembled from historical evidence (backfill/import)."""

    run = create_parse_run(db, asset=asset, config=config, reparse=True)
    run.status = "running"
    run.started_at = _now()
    states = engine_state()
    document.quality = assess(
        document, engines=states, doc_type=document.doc_type, notes=list(document.warnings),
    )
    document.seal()
    _replace_children(db, run, document)
    run.status = "completed"
    run.doc_type = document.doc_type
    run.parser_name = document.parser_name
    run.parser_version = document.parser_version
    run.config_version = document.config_version
    run.fingerprint = document.fingerprint
    run.page_count = document.page_count
    run.text_chars = document.quality.text_chars
    run.quality_status = document.quality.status
    run.quality_json = json.dumps(document.quality.to_dict(), ensure_ascii=False)
    run.markdown_text = render_markdown(document)
    run.finished_at = _now()
    run.error_code = run.error_message = None
    _promote_current(db, run)
    db.flush()
    return ParseOutcome(run=run, ir=document)


def _override(info: Any, *, available: bool) -> Any:
    from dataclasses import replace

    return replace(info, available=available)


def _replace_children(db: Session, run: DocumentParseRun, document: DocumentIR) -> None:
    """Idempotent write of one run's immutable children (retry safe)."""

    for model in (DocumentBlock, DocumentSection, DocumentChunk):
        db.query(model).filter(model.parse_run_id == run.id).delete(synchronize_session=False)
    db.query(DocumentPage).filter(DocumentPage.parse_run_id == run.id).delete(synchronize_session=False)
    db.flush()

    page_rows: dict[int, DocumentPage] = {}
    for page in document.pages:
        row = DocumentPage(
            id=new_id(), parse_run_id=run.id, page_number=page.page_number,
            width=page.width, height=page.height, rotation=page.rotation,
            render_key=page.render_key, extraction=page.extraction, status=page.status,
            text=page.text, confidence=page.confidence,
            warnings_json=json.dumps(page.warnings, ensure_ascii=False),
            fingerprint=None, created_at=_now(),
        )
        db.add(row)
        page_rows[page.page_number] = row
    db.flush()

    for page in document.pages:
        page_row = page_rows[page.page_number]
        for block in page.blocks:
            db.add(DocumentBlock(
                id=new_id(), parse_run_id=run.id, page_id=page_row.id,
                block_id=block.block_id, parent_block_id=block.parent_id,
                order=block.order, global_order=block.global_order,
                block_type=block.type, level=block.level, text=block.text,
                latex=block.latex,
                table_json=json.dumps(block.table.to_dict(), ensure_ascii=False) if block.table else None,
                figure_json=json.dumps(block.figure.to_dict(), ensure_ascii=False) if block.figure else None,
                bbox_json=json.dumps(block.bbox) if block.bbox else None,
                extraction=block.extraction, confidence=block.confidence,
                warnings_json=json.dumps(block.warnings, ensure_ascii=False),
                created_at=_now(),
            ))
    for section in document.sections:
        db.add(DocumentSection(
            id=new_id(), parse_run_id=run.id, section_id=section.section_id,
            order=section.order, title=section.title, level=section.level,
            page_start=section.page_start, page_end=section.page_end,
            block_ids_json=json.dumps(section.block_ids, ensure_ascii=False),
            created_at=_now(),
        ))
    for chunk in build_chunks(document):
        db.add(DocumentChunk(
            id=new_id(), parse_run_id=run.id, asset_id=document.asset_id,
            section_id=chunk.section_id, order=chunk.order, text=chunk.text,
            page_numbers_json=json.dumps(chunk.page_numbers),
            block_ids_json=json.dumps(chunk.block_ids), created_at=_now(),
        ))
    db.flush()


def _promote_current(db: Session, run: DocumentParseRun) -> None:
    db.execute(update(DocumentParseRun).where(
        DocumentParseRun.asset_id == run.asset_id,
        DocumentParseRun.id != run.id,
        DocumentParseRun.is_current.is_(True),
    ).values(is_current=False))
    run.is_current = True
    db.flush()


def fail_parse_run(
    db: Session, run_id: str, *, code: str, message: str,
) -> DocumentParseRun | None:
    run = db.get(DocumentParseRun, run_id)
    if run is None:
        return None
    if run.status == "completed":
        raise DocumentProcessingError("已完成的解析版本不可标记失败", code="parse_run_completed")
    run.status = "failed"
    run.error_code = code[:60]
    run.error_message = message[:2000]
    run.finished_at = _now()
    run.quality_status = "failed"
    run.quality_json = json.dumps({
        "status": "failed", "generation_allowed": False,
        "generation_block_reason": message[:2000],
    }, ensure_ascii=False)
    run.is_current = False
    db.flush()
    return run


def current_run(db: Session, asset_id: str, *, completed_only: bool = True) -> DocumentParseRun | None:
    query = select(DocumentParseRun).where(
        DocumentParseRun.asset_id == asset_id,
        DocumentParseRun.is_current.is_(True),
    )
    if completed_only:
        query = query.where(DocumentParseRun.status == "completed")
    return db.scalar(query)


def latest_run(db: Session, asset_id: str) -> DocumentParseRun | None:
    return db.scalar(select(DocumentParseRun).where(
        DocumentParseRun.asset_id == asset_id,
    ).order_by(DocumentParseRun.created_at.desc(), DocumentParseRun.id.desc()).limit(1))


def load_ir(db: Session, run: DocumentParseRun | str) -> DocumentIR:
    if isinstance(run, str):
        loaded = db.get(DocumentParseRun, run)
        if loaded is None:
            raise DocumentProcessingError("解析版本不存在", code="parse_run_missing")
        run = loaded
    page_rows = list(db.scalars(select(DocumentPage).where(
        DocumentPage.parse_run_id == run.id,
    ).order_by(DocumentPage.page_number)).all())
    block_rows = list(db.scalars(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id,
    ).order_by(DocumentBlock.global_order, DocumentBlock.order)).all())
    section_rows = list(db.scalars(select(DocumentSection).where(
        DocumentSection.parse_run_id == run.id,
    ).order_by(DocumentSection.order)).all())

    blocks_by_page: dict[str, list[BlockIR]] = {}
    for row in block_rows:
        blocks_by_page.setdefault(row.page_id, []).append(
            _block_from_row(row, run.asset_id))
    pages = [
        PageIR(
            page_id=row.id, page_number=row.page_number, width=row.width, height=row.height,
            rotation=row.rotation, render_key=row.render_key, extraction=row.extraction,
            status=row.status, text=row.text, confidence=row.confidence,
            warnings=_json_list(row.warnings_json),
            blocks=[
                _with_page(block, row.page_number, row.render_key, run.asset_id)
                for block in blocks_by_page.get(row.id, [])
            ],
        )
        for row in page_rows
    ]
    sections = [
        SectionIR(
            section_id=row.section_id, order=row.order, title=row.title, level=row.level,
            page_start=row.page_start, page_end=row.page_end,
            block_ids=_json_list(row.block_ids_json),
        )
        for row in section_rows
    ]
    document = DocumentIR(
        document_id=run.document_id, asset_id=run.asset_id, parse_run_id=run.id,
        doc_type=_doc_type(run), file_sha256=None,
        parser_name=run.parser_name, parser_version=run.parser_version,
        config_version=run.config_version, page_count=run.page_count,
        pages=pages, sections=sections,
        quality=QualityReport.from_dict(_json_dict(run.quality_json)),
        warnings=[], fingerprint=run.fingerprint,
    )
    return document


def _doc_type(run: DocumentParseRun) -> str:
    return run.doc_type if run.doc_type else "unknown"


def _with_page(
    block: BlockIR, page_number: int, render_key: str | None, asset_id: str,
) -> BlockIR:
    from app.document_processing.ir import SourceSpan

    block.page_number = page_number
    block.source = SourceSpan(
        asset_id=asset_id,
        page_number=page_number,
        bbox=block.bbox,
        render_key=render_key,
        location_label=block.source.location_label if block.source else None,
    )
    return block


def _block_from_row(row: DocumentBlock, asset_id: str) -> BlockIR:
    table = TableData.from_dict(_json_dict(row.table_json))
    figure = FigureData.from_dict(_json_dict(row.figure_json))
    bbox = _json_list(row.bbox_json)
    from app.document_processing.ir import SourceSpan

    return BlockIR(
        block_id=row.block_id, page_number=0, order=row.order, global_order=row.global_order,
        type=row.block_type, level=row.level, text=row.text, latex=row.latex,
        table=table, figure=figure,
        bbox=[float(item) for item in bbox] if len(bbox) == 4 else None,
        source=SourceSpan(asset_id=asset_id, page_number=0, bbox=None),
        extraction=row.extraction, confidence=row.confidence,
        warnings=_json_list(row.warnings_json), parent_id=row.parent_block_id,
    )


def chunks_for_run(db: Session, run_id: str) -> list[DocumentChunk]:
    return list(db.scalars(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run_id,
    ).order_by(DocumentChunk.order)).all())


def rebuild_views(db: Session, run_id: str) -> DocumentParseRun:
    """Recompute markdown/chunks for a run without touching its evidence rows."""

    run = db.get(DocumentParseRun, run_id)
    if run is None:
        raise DocumentProcessingError("解析版本不存在", code="parse_run_missing")
    document = load_ir(db, run)
    document.sections = document.sections or []
    db.query(DocumentChunk).filter(DocumentChunk.parse_run_id == run.id).delete(
        synchronize_session=False)
    for chunk in build_chunks(document):
        db.add(DocumentChunk(
            id=new_id(), parse_run_id=run.id, asset_id=run.asset_id,
            section_id=chunk.section_id, order=chunk.order, text=chunk.text,
            page_numbers_json=json.dumps(chunk.page_numbers),
            block_ids_json=json.dumps(chunk.block_ids), created_at=_now(),
        ))
    run.markdown_text = render_markdown(document)
    db.flush()
    return run


def page_render(db: Session, run: DocumentParseRun, page_number: int) -> Path | None:
    """Return an existing rendering, or render a text page on demand."""

    row = db.scalar(select(DocumentPage).where(
        DocumentPage.parse_run_id == run.id,
        DocumentPage.page_number == page_number,
    ))
    if row is None:
        return None
    if row.render_key:
        path = _safe_derived_path(row.render_key)
        if path is not None and path.is_file():
            return path
    asset = db.get(Asset, run.asset_id)
    if asset is None:
        return None
    source = _asset_path(asset)
    if not source.is_file() or (asset.extension or "").lower() != ".pdf":
        return None
    from app.document_processing.engines import pdf_text

    png = pdf_text.render_pdf_page(source, page_number)
    if png:
        key = _store_render(asset.id, run.id, page_number, png)
        row.render_key = key
        db.flush()
        return _safe_derived_path(key)
    return None


def _asset_path(asset: Asset) -> Path:
    root = settings.data_dir.resolve()
    candidate = (root / asset.storage_key).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise DocumentProcessingError("资源路径不合法", code="asset_path_invalid")
    return candidate


def _store_render(asset_id: str, run_id: str, page_number: int, png: bytes) -> str:
    key = f"derived/pages/{asset_id}/{run_id}/p{page_number}.png"
    path = _safe_derived_path(key)
    if path is None:
        raise DocumentProcessingError("渲染路径不合法", code="render_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(png)
    temporary.replace(path)
    return key


def _store_figure(asset_id: str, run_id: str, page_number: int, payload: bytes, suffix: str) -> str:
    import hashlib

    if suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    digest = hashlib.sha256(payload).hexdigest()[:20]
    key = f"derived/figures/{asset_id}/{run_id}/p{page_number}-{digest}{suffix.lower()}"
    path = _safe_derived_path(key)
    if path is None:
        raise DocumentProcessingError("图像证据路径不合法", code="figure_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return key


def _safe_derived_path(key: str) -> Path | None:
    root = settings.data_dir.resolve()
    try:
        candidate = (root / key).resolve()
    except (OSError, RuntimeError):
        return None
    if not candidate.is_relative_to(root) or candidate == root:
        return None
    return candidate


def _json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
