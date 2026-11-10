"""Local-first evidence reading; doubtful pages use the original vision reader.

The quality router is deliberately conservative. It never equates non-empty
text with correct formulas, tables or figures, and never writes Notebook body.
"""
from __future__ import annotations

import copy
import json
import logging
import re

from sqlalchemy import select

from app.ai.request_control import request_checkpoint
from app.db.models import NotebookAsset, ProcessingStep
from app.document_processing.adapters import mineru
from app.document_processing.adapters.pdf import ParseContext, _is_white_page, parse_pdf
from app.document_processing.checkpoints import fingerprint, put_step
from app.document_processing.config import asset_config, route_limits, vision_client
from app.document_processing.engines import pdf_text
from app.document_processing.engines.vision import (
    VisionCapabilityError,
    _settings,
    config_fingerprint,
    require_image_capability,
)
from app.document_processing.ir import DocumentIR, PageIR, QualityReport, SectionIR, SourceSpan
from app.document_processing.llm_reader import ReadingPending, read_page_image, reading_page
from app.document_processing.rendering import page_images
from app.services.processing_budget import processing_budget_scope

logger = logging.getLogger(__name__)
POLICY_VERSION = 'hybrid-v1'
_MATH = re.compile(r'[=<>≤≥∑∫√±∞²³¹\u2070-\u209f]|[A-Za-z]\s*[_^]|\\[A-Za-z]+|[A-Za-z0-9]\s*[+−]\s*[A-Za-z0-9]')


def page_needs_vision(page: PageIR) -> list[str]:
    reasons = []
    if page.status != 'parsed' or not page.blocks:
        reasons.append('page_incomplete')
    if page.rotation:
        reasons.append('reading_order_uncertain')
    if any(warning.startswith('native_math_geometry:') for warning in page.warnings):
        reasons.append('math_geometry_uncertain')
    if any(warning.startswith('native_small_visual:') for warning in page.warnings):
        reasons.append('small_visual_unchecked')
    if any(warning.startswith(('native_vector_content:', 'native_layout_unavailable:')) for warning in page.warnings):
        reasons.append('layout_evidence_uncertain')
    if page.confidence is not None and page.confidence < 0.85:
        reasons.append('low_confidence')
    for block in page.blocks:
        text = block.searchable_text()
        if any(c == '\ufffd' or 0xE000 <= ord(c) <= 0xF8FF or
               (ord(c) < 32 and c not in '\n\r\t') for c in text):
            reasons.append('broken_glyphs')
        if len(text) > 100_000:
            reasons.append('oversized_block')
        if block.type == 'equation' and not block.latex:
            reasons.append('formula_missing')
        if block.type in {'paragraph', 'list', 'list_item', 'caption', 'unknown'} and _MATH.search(text):
            # Native text runs cannot prove superscripts/fractions were retained.
            reasons.append('inline_math_uncertain')
        if block.type == 'table' and (not block.table or not block.table.rows or
                not any(cell.strip() for row in block.table.rows for cell in row)):
            reasons.append('table_missing')
        if block.type in {'figure', 'image'} and (block.extraction != 'vision' or
                not block.figure or block.figure.uncertain or
                not (block.figure.description or block.figure.nodes or block.figure.latex)):
            reasons.append('figure_uncertain')
        if block.confidence is not None and block.confidence < 0.85:
            reasons.append('low_block_confidence')
        if block.warnings:
            reasons.append('block_warning')
    return sorted(set(reasons))


def local_pages(path, context, *, page_numbers=None) -> dict[int, PageIR]:
    if path.suffix.lower() != '.pdf':
        return {}
    # No remote vision and no model downloads in the native first pass.
    document = parse_pdf(path, context, ocr_available=False, vision_available=False,
                         page_numbers=page_numbers, strict_evidence=True)
    if pdf_text._pymupdf() is None:
        for page in document.pages:
            page.warnings.append('native_layout_unavailable: 缺少字体和版面证据，不能证明公式完整')
    return {page.page_number: page for page in document.pages}


def enhance_page(path, context, number, *, tier='basic') -> PageIR | None:
    if path.suffix.lower() not in {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}:
        # Office local page indices need not match Word/PowerPoint's converted
        # preview pages. Keep the existing visual path rather than misattribute.
        return None
    if not mineru.availability()['available']:
        return None
    document = mineru.parse_document(path, context, page_numbers=[number], tier=tier, local_only=True)
    return next((p for p in document.pages if p.page_number == number), None)


def _active(db, run):
    db.refresh(run)
    if run.status != 'running':
        raise RuntimeError('资料处理已停止，未缓存或提交本次读取结果')


def read_hybrid_document(db, run, asset, path, *, progress=None, max_new_pages=None):
    config = asset_config(asset)
    vision = _settings(config.get('vision'))
    if config.get('vision_capability_fingerprint') != config_fingerprint(vision):
        raise VisionCapabilityError('资料中的视觉模型快照校验失败，已阻止付费读取')
    require_image_capability(vision)
    client = vision_client(config, vision)
    def check_request():
        _active(db, run)
        if progress:
            progress(len(cached), count)
        db.commit()
    context = ParseContext(asset_id=asset.id, parse_run_id=run.id,
        file_sha256=asset.sha256, doc_type='pdf' if path.suffix.lower() == '.pdf' else 'image')
    engine_identity = [pdf_text.availability().to_dict(), mineru.availability()]
    identity_base = [asset.sha256, config, engine_identity, POLICY_VERSION]
    with page_images(path, asset.id, route_limits('llm')[1]) as (count, render):
        run.page_count = count
        db.commit()
        identities = {n: fingerprint([identity_base, n]) for n in range(1, count + 1)}
        cached = {int(row.step_key): json.loads(row.result_json) for row in db.scalars(
            select(ProcessingStep).where(ProcessingStep.scope == asset.id,
                                         ProcessingStep.stage == 'hybrid-read'))
            if row.step_key.isdigit() and identities.get(int(row.step_key)) == row.fingerprint}
        unread = [n for n in identities if n not in cached]
        selected = unread if max_new_pages is None else unread[:max_new_pages]
        candidates = {}
        if selected:
            try:
                candidates = local_pages(path, context, page_numbers=selected)
            except Exception as exc:
                logger.warning('hybrid_native_unavailable error_type=%s', type(exc).__name__)
        if progress:
            progress(len(cached), count)
        for number in selected:
            _active(db, run)
            if progress:
                progress(len(cached), count)
            candidate = candidates.get(number)
            reasons = page_needs_vision(candidate) if candidate else ['local_parse_missing']
            png = None
            # Validate blankness against the original raster, not a parser label.
            if candidate is None or not candidate.blocks:
                png = render(number)
                if _is_white_page(png):
                    candidate = PageIR(page_id='', page_number=number, status='empty',
                                       extraction='native_text')
                    reasons = []
            # Do not let a second text-only extraction erase evidence that the
            # first pass detected but could not structurally explain.
            original_risks = {'math_geometry_uncertain', 'small_visual_unchecked',
                              'layout_evidence_uncertain'} & set(reasons)
            if reasons and not original_risks:
                try:
                    enhanced = enhance_page(path, context, number, tier=config.get('local_tier', 'basic'))
                    if enhanced is not None and not page_needs_vision(enhanced):
                        candidate, reasons = enhanced, []
                except Exception as exc:
                    # Local models are optional; an unavailable engine must not
                    # prevent the original, budgeted visual fallback.
                    logger.warning('hybrid_local_unavailable page=%s error_type=%s', number, type(exc).__name__)
            _active(db, run)
            strategy = 'local'
            usage = None
            if reasons:
                png = png or render(number)
                owner = db.scalar(select(NotebookAsset.notebook_id).where(
                    NotebookAsset.asset_id == asset.id, NotebookAsset.is_owner.is_(True),
                    NotebookAsset.detached_at.is_(None)))
                if not owner:
                    raise RuntimeError('资料没有有效 Notebook 预算归属')
                db.commit()
                with request_checkpoint(check_request), processing_budget_scope(asset_ids=[asset.id], notebook_id=owner,
                        stage='read', job_id=run.id, step_key=str(number), kind='vision'):
                    parsed = read_page_image(client, png, number)
                if progress:
                    progress(len(cached), count)
                _active(db, run)
                if any(block.uncertain for block in parsed.blocks):
                    raise ValueError(f'第 {number} 页视觉读取仍有不确定内容，请核对原页')
                if parsed.status == 'blank' and not _is_white_page(png):
                    raise ValueError(f'第 {number} 页可见内容与空白识别矛盾')
                candidate = reading_page(parsed, run, asset, number, 0)
                strategy, usage = 'vision', client.last_usage
            if png is not None:
                from app.document_processing.service import _store_render
                candidate.render_key = _store_render(asset.id, run.id, number, png)
            put_step(db, asset.id, 'hybrid-read', str(number), identities[number],
                     {'page': candidate.to_dict(), 'strategy': strategy, 'reasons': reasons}, usage)
            cached[number] = {'page': candidate.to_dict(), 'strategy': strategy, 'reasons': reasons}
            if progress:
                progress(len(cached), count)
        if len(selected) < len(unread):
            raise ReadingPending()
        pages, global_order = [], 0
        for number in range(1, count + 1):
            page = PageIR.from_dict(copy.deepcopy(cached[number]['page']))
            page.page_id = f'{run.id}-p{number}'
            page.page_number = number
            for order, block in enumerate(page.blocks):
                block.block_id = f'{run.id[:8]}-p{number}-b{order+1}'
                block.page_number, block.order, block.global_order = number, order, global_order
                block.source = SourceSpan(asset_id=asset.id, page_number=number, bbox=block.bbox,
                    render_key=page.render_key, location_label=(f'转换预览第 {number} 页'
                        if asset.extension == '.docx' else f'第 {number} 页'))
                global_order += 1
            pages.append(page)
    document = DocumentIR(document_id=asset.id, asset_id=asset.id, parse_run_id=run.id,
        doc_type=asset.extension.lstrip('.'), file_sha256=asset.sha256,
        parser_name='hybrid-local-vision', parser_version='1', config_version=POLICY_VERSION,
        page_count=count, pages=pages, sections=[], quality=QualityReport())
    from app.document_processing.normalization.blocks import normalize_standard_blocks

    normalize_standard_blocks(document)
    document.sections = [SectionIR(section_id=f'p{p.page_number}', order=i, title=f'第 {p.page_number} 页',
        page_start=p.page_number, page_end=p.page_number, block_ids=[b.block_id for b in p.blocks])
        for i, p in enumerate(document.pages) if p.blocks]
    return document
