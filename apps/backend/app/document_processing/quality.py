"""Structured parse quality assessment.

Content length is not a proxy for usefulness: a short exercise, formula, or
table can be valid. Generation is admitted based on usable content and page
state; unresolved OCR and failed pages remain blocking issues.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.document_processing.engines.pdf_text import EngineInfo
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    QualityIssue,
    QualityReport,
)

_PLACEHOLDER_TEXT = {"原始图片（未识别文字）", "图像内容未解析"}


@dataclass
class EngineState:
    ocr: EngineInfo
    vision: EngineInfo


def _page_blocks(document: DocumentIR) -> list[tuple[int, list[BlockIR], str]]:
    return [(page.page_number, page.blocks, page.text) for page in document.pages]


def _has_structure(blocks: list[BlockIR]) -> bool:
    return any(
        (block.type == "table" and block.table and any(any(cell.strip() for cell in row)
                                                        for row in block.table.rows))
        or (block.type == "equation" and (block.latex or block.text).strip())
        or (block.type == "figure" and block.figure and (
            block.figure.description or block.figure.latex or block.figure.nodes
        ))
        for block in blocks
    )


def _page_content(page) -> str:
    if page.text.strip() not in _PLACEHOLDER_TEXT and page.text.strip():
        return page.text.strip()
    parts: list[str] = []
    for block in page.blocks:
        if block.type == "image":
            continue
        if block.type == "table" and block.table:
            parts.extend(cell for row in block.table.rows for cell in row if cell.strip())
        elif block.type == "figure" and block.figure:
            parts.extend([block.figure.description or "", block.figure.latex or ""])
            parts.extend(block.figure.nodes)
            parts.extend(block.figure.edges)
        else:
            parts.extend([block.text, block.latex or ""])
    return "\n".join(part.strip() for part in parts if part.strip())


def assess(
    document: DocumentIR,
    *,
    engines: EngineState,
    doc_type: str,
    notes: list[str] | None = None,
) -> QualityReport:
    issues: list[QualityIssue] = []
    pages_total = len(document.pages)
    pages_ok = 0
    pages_empty = 0
    pages_failed = 0
    text_chars = 0
    confidences: list[float] = []
    needs_ocr_pages: list[int] = []
    needs_vision_pages: list[int] = []
    failed_pages: list[int] = []
    empty_pages: list[int] = []
    rotated_pages: list[int] = []
    unstructured_tables: list[int] = []
    unlabelled_equations: list[int] = []
    unexplained_figures: list[int] = []

    for page in document.pages:
        page_text = _page_content(page)
        blocks = page.blocks
        page_chars = len(page_text)
        text_chars += page_chars
        usable = bool(page_text) or _has_structure(blocks)
        if page.status == "failed":
            pages_failed += 1
            failed_pages.append(page.page_number)
        if usable:
            pages_ok += 1
        elif page.status != "failed":
            pages_empty += 1
            empty_pages.append(page.page_number)
        if page.status == "needs_ocr":
            needs_ocr_pages.append(page.page_number)
        if page.status == "needs_vision":
            needs_vision_pages.append(page.page_number)
        if page.rotation:
            rotated_pages.append(page.page_number)
        if page.confidence is not None:
            confidences.append(page.confidence)
        for block in blocks:
            if block.type == "table" and block.table is None:
                unstructured_tables.append(page.page_number)
            if block.type == "equation" and not (block.latex or "").strip():
                unlabelled_equations.append(page.page_number)
            if block.type == "figure" and block.figure and not (
                block.figure.description or block.figure.nodes or block.figure.latex
            ):
                unexplained_figures.append(page.page_number)

    if needs_ocr_pages:
        issues.append(QualityIssue(
            code="ocr_required",
            severity="blocking",
            message=(
                f"第 {_ranges(needs_ocr_pages)} 页没有可提取文字，需要 OCR"
                + ("；当前环境没有可用 OCR 引擎" if not engines.ocr.available else "")
            ),
            page_numbers=needs_ocr_pages,
            retry_hint=(
                "安装并启用 OCR 引擎（rapidocr_onnxruntime 或 tesseract）后重新解析；"
                "或上传带文字层的 PDF/更清晰的图片"
                if not engines.ocr.available else "重新解析以使用 OCR 结果"
            ),
        ))
    if needs_vision_pages:
        issues.append(QualityIssue(
            code="vision_required",
            severity="warning",
            message=(
                f"第 {_ranges(needs_vision_pages)} 页含需要视觉理解的公式/表格/图形"
                + ("；当前未配置视觉引擎" if not engines.vision.available else "")
            ),
            page_numbers=needs_vision_pages,
            retry_hint=(
                "配置 NOTEBOOK_VISION_* 视觉服务后重新解析，或人工核对原图"
                if not engines.vision.available else "重新解析以使用视觉结果"
            ),
        ))
    if failed_pages:
        issues.append(QualityIssue(
            code="page_failed", severity="blocking",
            message=f"第 {_ranges(failed_pages)} 页解析失败", page_numbers=failed_pages,
        ))
    if empty_pages:
        issues.append(QualityIssue(
            code="empty_pages", severity="warning",
            message=f"第 {_ranges(empty_pages)} 页没有可用文字或结构，可能被跳过",
            page_numbers=empty_pages,
            retry_hint="核对空白页是否为原资料本身的空白；否则启用 OCR/视觉识别",
        ))
    if unstructured_tables:
        issues.append(QualityIssue(
            code="table_structure_lost", severity="warning",
            message=f"第 {_ranges(unstructured_tables)} 页的表格未能结构化，仅保留文本",
            page_numbers=unstructured_tables, retry_hint="人工核对表格，或启用视觉识别",
        ))
    if unlabelled_equations:
        issues.append(QualityIssue(
            code="formula_structure_uncertain", severity="warning",
            message=f"第 {_ranges(unlabelled_equations)} 页识别到公式，但未能还原 LaTeX 结构",
            page_numbers=unlabelled_equations, retry_hint="启用视觉引擎或人工补录公式",
        ))
    if unexplained_figures:
        issues.append(QualityIssue(
            code="figure_not_interpreted", severity="warning",
            message=f"第 {_ranges(unexplained_figures)} 页含未解释的图表/示意图",
            page_numbers=unexplained_figures, retry_hint="启用视觉引擎或人工核对原图",
        ))
    if rotated_pages:
        issues.append(QualityIssue(
            code="page_rotation", severity="info",
            message=f"第 {_ranges(rotated_pages)} 页存在旋转，阅读顺序可能受影响",
            page_numbers=rotated_pages,
        ))
    if doc_type in {"pptx", "docx"}:
        issues.append(QualityIssue(
            code="office_limited", severity="warning",
            message="PPTX/DOCX 仅提供基础解析，本轮不保证公式、图表与版式质量",
            retry_hint="优先上传 PDF 或图片以获得完整解析",
        ))
    if notes:
        issues.extend(QualityIssue(code="parser_note", severity="info", message=text)
                      for text in notes[:20])

    if pages_total == 0:
        return QualityReport(
            status="failed", pages_total=0, issues=issues,
            generation_block_reason="文档没有可解析页面",
        )

    if pages_ok == 0:
        status = "needs_ocr" if needs_ocr_pages else "needs_vision" if needs_vision_pages else "failed"
        reason = (
            "解析未得到任何可用文字。"
            + ("需要 OCR：" + _ranges(needs_ocr_pages) + " 页。" if needs_ocr_pages else "")
            + ("需要视觉识别：" + _ranges(needs_vision_pages) + " 页。" if needs_vision_pages else "")
            + "为避免生成空泛或伪造的笔记，已阻止自动生成。"
        )
        return QualityReport(
            status=status, score=0.0, pages_total=pages_total, pages_ok=0,
            pages_empty=pages_total - pages_failed, pages_failed=pages_failed,
            text_chars=text_chars, text_chars_per_page=text_chars / pages_total, issues=issues,
            usable_page_ranges=[],
            generation_allowed=False, generation_block_reason=reason,
        )

    blocking = [issue for issue in issues if issue.severity == "blocking"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    status = "partial" if (blocking or warnings) else "complete"
    coverage = pages_ok / pages_total
    structure = 0.0
    if any(block.type == "heading" for block in document.all_blocks()):
        structure += 0.5
    if any(block.type == "table" and block.table for block in document.all_blocks()) or not any(block.type == "table" for block in document.all_blocks()):
        structure += 0.2
    if not unexplained_figures and not unlabelled_equations:
        structure += 0.3
    elif not unexplained_figures or not unlabelled_equations:
        structure += 0.15
    confidence = sum(confidences) / len(confidences) if confidences else 0.6
    score = 0.45 * coverage + 0.25 * structure + 0.20 * confidence + 0.10 * (0.0 if blocking else 1.0)

    ranges = _usable_ranges(document)
    generation_allowed = bool(ranges) and not blocking and status in {"complete", "partial"}
    reason = None
    if not generation_allowed:
        reason = "解析结果不可用于生成正式正文，请检查失败页面与解析质量"

    return QualityReport(
        status=status,
        score=max(0.0, min(score, 1.0)),
        pages_total=pages_total,
        pages_ok=pages_ok,
        pages_empty=pages_empty,
        pages_failed=pages_failed,
        text_chars=text_chars,
        text_chars_per_page=text_chars / pages_total,
        issues=issues,
        usable_page_ranges=ranges,
        generation_allowed=generation_allowed,
        generation_block_reason=reason,
    )


def _usable_ranges(document: DocumentIR) -> list[list[int]]:
    usable: list[int] = []
    for page in document.pages:
        if page.status != "failed" and (_page_content(page) or _has_structure(page.blocks)):
            usable.append(page.page_number)
    ranges: list[list[int]] = []
    for number in usable:
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ranges


def _ranges(pages: list[int]) -> str:
    if not pages:
        return ""
    ordered = sorted(set(pages))
    parts: list[str] = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(f"{start}" if start == previous else f"{start}–{previous}")
        start = previous = number
    parts.append(f"{start}" if start == previous else f"{start}–{previous}")
    return "、".join(parts)
