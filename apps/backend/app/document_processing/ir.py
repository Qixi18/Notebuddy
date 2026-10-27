"""Document IR v1: the normalized, versioned, source-located parse model.

The IR is the single contract between parsers and everything downstream
(Notebook generation, retrieval, quality reporting, agent evidence).  Parsers
must not write business documents directly; they produce an IR which is stored
as one immutable parse run.

Design rules:
- Every content block keeps a stable ``block_id`` inside its parse run, its
  page number, reading order, extraction method and (when available) a page
  bounding box so a Notebook block can be traced back to the source.
- Pages are evidence/source-location units, not the organization boundary of
  the generated learning note.  Sections group blocks across pages.
- Quality is structured and explicit: "parse finished" is not "usable".
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

IR_VERSION = 1

BLOCK_TYPES = {
    "heading",
    "paragraph",
    "list",
    "list_item",
    "code",
    "equation",
    "table",
    "figure",
    "image",
    "caption",
    "unknown",
}

EXTRACTIONS = {"native_text", "ocr", "vision", "heuristic", "mixed", "none"}

PAGE_STATUSES = {
    "parsed",
    "partial",
    "needs_ocr",
    "needs_vision",
    "empty",
    "failed",
}

QUALITY_STATUSES = {
    "complete",
    "partial",
    "needs_ocr",
    "needs_vision",
    "failed",
}

ISSUE_SEVERITIES = {"blocking", "warning", "info"}

FIGURE_KINDS = {"diagram", "chart", "circuit", "photo", "formula", "table", "other"}


class IRValidationError(ValueError):
    """Raised when an IR payload violates the contract."""


def _clean(value: Any, limit: int = 200_000) -> str:
    text = value if isinstance(value, str) else ""
    return text[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class SourceSpan:
    asset_id: str
    page_number: int
    bbox: list[float] | None = None
    render_key: str | None = None
    location_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "page_number": self.page_number,
            "bbox": list(self.bbox) if self.bbox else None,
            "render_key": self.render_key,
            "location_label": self.location_label,
        }

    @classmethod
    def from_dict(cls, data: Any) -> SourceSpan | None:
        if not isinstance(data, dict):
            return None
        asset_id = data.get("asset_id")
        page_number = data.get("page_number")
        if not isinstance(asset_id, str) or not isinstance(page_number, int):
            return None
        bbox = data.get("bbox")
        return cls(
            asset_id=asset_id,
            page_number=page_number,
            bbox=[float(item) for item in bbox] if isinstance(bbox, list) and len(bbox) == 4 else None,
            render_key=data.get("render_key") if isinstance(data.get("render_key"), str) else None,
            location_label=data.get("location_label") if isinstance(data.get("location_label"), str) else None,
        )


@dataclass
class TableData:
    rows: list[list[str]] = field(default_factory=list)
    header_rows: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [[_clean(cell, 2_000) for cell in row] for row in self.rows],
            "header_rows": max(0, min(int(self.header_rows), len(self.rows))),
        }

    @classmethod
    def from_dict(cls, data: Any) -> TableData | None:
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            return None
        rows = []
        for row in data["rows"]:
            if isinstance(row, list):
                rows.append([str(cell) for cell in row])
        if not rows:
            return None
        header = data.get("header_rows")
        return cls(rows=rows, header_rows=header if isinstance(header, int) else 1)


@dataclass
class FigureData:
    kind: str = "other"
    description: str | None = None
    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    latex: str | None = None
    uncertain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind if self.kind in FIGURE_KINDS else "other",
            "description": _clean(self.description, 5_000) if self.description else None,
            "nodes": [_clean(node, 300) for node in self.nodes[:200]],
            "edges": [_clean(edge, 300) for edge in self.edges[:400]],
            "latex": _clean(self.latex, 5_000) if self.latex else None,
            "uncertain": bool(self.uncertain),
        }

    @classmethod
    def from_dict(cls, data: Any) -> FigureData | None:
        if not isinstance(data, dict):
            return None
        kind = data.get("kind") if data.get("kind") in FIGURE_KINDS else "other"
        return cls(
            kind=kind,
            description=data.get("description") if isinstance(data.get("description"), str) else None,
            nodes=[str(item) for item in data.get("nodes") or [] if isinstance(item, (str, int, float))],
            edges=[str(item) for item in data.get("edges") or [] if isinstance(item, (str, int, float))],
            latex=data.get("latex") if isinstance(data.get("latex"), str) else None,
            uncertain=bool(data.get("uncertain")),
        )


@dataclass
class BlockIR:
    block_id: str
    page_number: int
    order: int
    global_order: int
    type: str = "paragraph"
    level: int = 0
    text: str = ""
    latex: str | None = None
    table: TableData | None = None
    figure: FigureData | None = None
    bbox: list[float] | None = None
    source: SourceSpan | None = None
    extraction: str = "native_text"
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    parent_id: str | None = None

    @property
    def text_length(self) -> int:
        return len(self.text.strip())

    def searchable_text(self) -> str:
        parts = [self.text]
        if self.latex:
            parts.append(self.latex)
        if self.table:
            parts.extend(" ".join(row) for row in self.table.rows)
        if self.figure:
            if self.figure.description:
                parts.append(self.figure.description)
            if self.figure.latex:
                parts.append(self.figure.latex)
            parts.extend(self.figure.nodes)
            parts.extend(self.figure.edges)
        return "\n".join(part for part in parts if part).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_number": self.page_number,
            "order": self.order,
            "global_order": self.global_order,
            "type": self.type if self.type in BLOCK_TYPES else "unknown",
            "level": max(0, min(int(self.level), 6)),
            "text": _clean(self.text),
            "latex": _clean(self.latex, 5_000) if self.latex else None,
            "table": self.table.to_dict() if self.table else None,
            "figure": self.figure.to_dict() if self.figure else None,
            "bbox": list(self.bbox) if self.bbox else None,
            "source": self.source.to_dict() if self.source else None,
            "extraction": self.extraction if self.extraction in EXTRACTIONS else "none",
            "confidence": _number(self.confidence),
            "warnings": [_clean(item, 500) for item in self.warnings[:20]],
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> BlockIR:
        if not isinstance(data, dict):
            raise IRValidationError("block must be an object")
        block_id = data.get("block_id")
        if not isinstance(block_id, str) or not block_id.strip():
            raise IRValidationError("block_id is required")
        page_number = data.get("page_number")
        if not isinstance(page_number, int) or page_number < 1:
            raise IRValidationError("page_number must be a positive integer")
        bbox = data.get("bbox")
        return cls(
            block_id=block_id[:64],
            page_number=page_number,
            order=int(data.get("order") or 0),
            global_order=int(data.get("global_order") or 0),
            type=data.get("type") if data.get("type") in BLOCK_TYPES else "unknown",
            level=int(data.get("level") or 0),
            text=_clean(data.get("text")),
            latex=data.get("latex") if isinstance(data.get("latex"), str) else None,
            table=TableData.from_dict(data.get("table")),
            figure=FigureData.from_dict(data.get("figure")),
            bbox=[float(item) for item in bbox] if isinstance(bbox, list) and len(bbox) == 4 else None,
            source=SourceSpan.from_dict(data.get("source")),
            extraction=data.get("extraction") if data.get("extraction") in EXTRACTIONS else "none",
            confidence=_number(data.get("confidence")),
            warnings=[str(item) for item in data.get("warnings") or [] if isinstance(item, str)],
            parent_id=data.get("parent_id") if isinstance(data.get("parent_id"), str) else None,
        )


@dataclass
class PageIR:
    page_id: str
    page_number: int
    width: float | None = None
    height: float | None = None
    rotation: int = 0
    render_key: str | None = None
    extraction: str = "native_text"
    status: str = "parsed"
    text: str = ""
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    blocks: list[BlockIR] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_number": self.page_number,
            "width": float(self.width) if self.width is not None else None,
            "height": float(self.height) if self.height is not None else None,
            "rotation": self.rotation,
            "render_key": self.render_key,
            "extraction": self.extraction if self.extraction in EXTRACTIONS else "none",
            "status": self.status if self.status in PAGE_STATUSES else "failed",
            "text": _clean(self.text),
            "confidence": _number(self.confidence),
            "warnings": [_clean(item, 500) for item in self.warnings[:20]],
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: Any) -> PageIR:
        if not isinstance(data, dict):
            raise IRValidationError("page must be an object")
        page_number = data.get("page_number")
        if not isinstance(page_number, int) or page_number < 1:
            raise IRValidationError("page_number must be a positive integer")
        return cls(
            page_id=str(data.get("page_id") or f"p{page_number}"),
            page_number=page_number,
            width=_number(data.get("width")),
            height=_number(data.get("height")),
            rotation=int(data.get("rotation") or 0),
            render_key=data.get("render_key") if isinstance(data.get("render_key"), str) else None,
            extraction=data.get("extraction") if data.get("extraction") in EXTRACTIONS else "none",
            status=data.get("status") if data.get("status") in PAGE_STATUSES else "failed",
            text=_clean(data.get("text")),
            confidence=_number(data.get("confidence")),
            warnings=[str(item) for item in data.get("warnings") or [] if isinstance(item, str)],
            blocks=[BlockIR.from_dict(item) for item in data.get("blocks") or []],
        )


@dataclass
class SectionIR:
    section_id: str
    order: int
    title: str
    level: int = 0
    page_start: int = 1
    page_end: int = 1
    block_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "order": self.order,
            "title": _clean(self.title, 500),
            "level": max(0, min(int(self.level), 6)),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "block_ids": list(self.block_ids),
        }

    @classmethod
    def from_dict(cls, data: Any) -> SectionIR:
        if not isinstance(data, dict):
            raise IRValidationError("section must be an object")
        return cls(
            section_id=str(data.get("section_id") or "sec-1"),
            order=int(data.get("order") or 0),
            title=str(data.get("title") or ""),
            level=int(data.get("level") or 0),
            page_start=int(data.get("page_start") or 1),
            page_end=int(data.get("page_end") or 1),
            block_ids=[str(item) for item in data.get("block_ids") or [] if isinstance(item, str)],
        )


@dataclass
class QualityIssue:
    code: str
    severity: str = "warning"
    message: str = ""
    page_numbers: list[int] = field(default_factory=list)
    retry_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity if self.severity in ISSUE_SEVERITIES else "warning",
            "message": _clean(self.message, 2_000),
            "page_numbers": sorted({int(item) for item in self.page_numbers if isinstance(item, int)}),
            "retry_hint": self.retry_hint,
        }

    @classmethod
    def from_dict(cls, data: Any) -> QualityIssue | None:
        if not isinstance(data, dict) or not isinstance(data.get("code"), str):
            return None
        return cls(
            code=data["code"],
            severity=data.get("severity") if data.get("severity") in ISSUE_SEVERITIES else "warning",
            message=str(data.get("message") or ""),
            page_numbers=[int(item) for item in data.get("page_numbers") or [] if isinstance(item, int)],
            retry_hint=data.get("retry_hint") if isinstance(data.get("retry_hint"), str) else None,
        )


@dataclass
class QualityReport:
    status: str = "failed"
    score: float = 0.0
    pages_total: int = 0
    pages_ok: int = 0
    pages_empty: int = 0
    pages_failed: int = 0
    text_chars: int = 0
    text_chars_per_page: float = 0.0
    issues: list[QualityIssue] = field(default_factory=list)
    usable_page_ranges: list[list[int]] = field(default_factory=list)
    generation_allowed: bool = False
    generation_block_reason: str | None = None

    def has_blocking(self) -> bool:
        return any(issue.severity == "blocking" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status if self.status in QUALITY_STATUSES else "failed",
            "score": round(float(self.score), 4),
            "pages_total": self.pages_total,
            "pages_ok": self.pages_ok,
            "pages_empty": self.pages_empty,
            "pages_failed": self.pages_failed,
            "text_chars": self.text_chars,
            "text_chars_per_page": round(float(self.text_chars_per_page), 2),
            "issues": [issue.to_dict() for issue in self.issues],
            "usable_page_ranges": self.usable_page_ranges,
            "generation_allowed": bool(self.generation_allowed),
            "generation_block_reason": self.generation_block_reason,
        }

    @classmethod
    def from_dict(cls, data: Any) -> QualityReport:
        if not isinstance(data, dict):
            return cls()
        return cls(
            status=data.get("status") if data.get("status") in QUALITY_STATUSES else "failed",
            score=_number(data.get("score")) or 0.0,
            pages_total=int(data.get("pages_total") or 0),
            pages_ok=int(data.get("pages_ok") or 0),
            pages_empty=int(data.get("pages_empty") or 0),
            pages_failed=int(data.get("pages_failed") or 0),
            text_chars=int(data.get("text_chars") or 0),
            text_chars_per_page=_number(data.get("text_chars_per_page")) or 0.0,
            issues=[issue for item in data.get("issues") or [] if (issue := QualityIssue.from_dict(item))],
            usable_page_ranges=[
                [int(pair[0]), int(pair[1])]
                for pair in data.get("usable_page_ranges") or []
                if isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, int) for v in pair)
            ],
            generation_allowed=bool(data.get("generation_allowed")),
            generation_block_reason=data.get("generation_block_reason") if isinstance(
                data.get("generation_block_reason"), str) else None,
        )


@dataclass
class DocumentIR:
    document_id: str
    asset_id: str
    parse_run_id: str
    doc_type: str
    file_sha256: str | None = None
    parser_name: str = "unknown"
    parser_version: str = "0"
    config_version: str = "v1"
    page_count: int = 0
    pages: list[PageIR] = field(default_factory=list)
    sections: list[SectionIR] = field(default_factory=list)
    quality: QualityReport = field(default_factory=QualityReport)
    warnings: list[str] = field(default_factory=list)
    ir_version: int = IR_VERSION
    fingerprint: str = ""

    # -- derived helpers -------------------------------------------------
    def all_blocks(self) -> Iterable[BlockIR]:
        for page in self.pages:
            yield from page.blocks

    def block_by_id(self, block_id: str) -> BlockIR | None:
        for block in self.all_blocks():
            if block.block_id == block_id:
                return block
        return None

    def block_text(self, block_id: str) -> str:
        block = self.block_by_id(block_id)
        return block.searchable_text() if block else ""

    def section_blocks(self, section: SectionIR) -> list[BlockIR]:
        wanted = set(section.block_ids)
        return [block for block in self.all_blocks() if block.block_id in wanted]

    def plain_text(self, *, include_tables: bool = True) -> str:
        lines: list[str] = []
        for block in self.all_blocks():
            text = block.searchable_text()
            if not text and not include_tables:
                continue
            if text:
                lines.append(text)
        return "\n\n".join(lines)

    # -- serialization ---------------------------------------------------
    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload = {
            "ir_version": self.ir_version,
            "document_id": self.document_id,
            "asset_id": self.asset_id,
            "parse_run_id": self.parse_run_id,
            "doc_type": self.doc_type,
            "file_sha256": self.file_sha256,
            "parser": {
                "name": self.parser_name,
                "version": self.parser_version,
                "config_version": self.config_version,
            },
            "page_count": self.page_count,
            "pages": [page.to_dict() for page in self.pages],
            "sections": [section.to_dict() for section in self.sections],
            "quality": self.quality.to_dict(),
            "warnings": [_clean(item, 1_000) for item in self.warnings[:100]],
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> DocumentIR:
        if not isinstance(data, dict):
            raise IRValidationError("document must be an object")
        parser = data.get("parser") if isinstance(data.get("parser"), dict) else {}
        document = cls(
            document_id=str(data.get("document_id") or ""),
            asset_id=str(data.get("asset_id") or ""),
            parse_run_id=str(data.get("parse_run_id") or ""),
            doc_type=str(data.get("doc_type") or "unknown"),
            file_sha256=data.get("file_sha256") if isinstance(data.get("file_sha256"), str) else None,
            parser_name=str(parser.get("name") or "unknown"),
            parser_version=str(parser.get("version") or "0"),
            config_version=str(parser.get("config_version") or "v1"),
            page_count=int(data.get("page_count") or 0),
            pages=[PageIR.from_dict(item) for item in data.get("pages") or []],
            sections=[SectionIR.from_dict(item) for item in data.get("sections") or []],
            quality=QualityReport.from_dict(data.get("quality")),
            warnings=[str(item) for item in data.get("warnings") or [] if isinstance(item, str)],
            ir_version=int(data.get("ir_version") or IR_VERSION),
            fingerprint=str(data.get("fingerprint") or ""),
        )
        document.validate()
        return document

    # -- validation ------------------------------------------------------
    def validate(self) -> DocumentIR:
        if not self.asset_id:
            raise IRValidationError("asset_id is required")
        if not self.parse_run_id:
            raise IRValidationError("parse_run_id is required")
        if self.page_count not in (0, len(self.pages)):
            raise IRValidationError("page_count must match pages")
        seen_pages: set[int] = set()
        seen_blocks: set[str] = set()
        for page in self.pages:
            if page.page_number in seen_pages:
                raise IRValidationError(f"duplicate page number: {page.page_number}")
            seen_pages.add(page.page_number)
            for block in page.blocks:
                if block.page_number != page.page_number:
                    raise IRValidationError(
                        f"block {block.block_id} page mismatch ({block.page_number} != {page.page_number})"
                    )
                if block.block_id in seen_blocks:
                    raise IRValidationError(f"duplicate block id: {block.block_id}")
                seen_blocks.add(block.block_id)
                if block.type == "table" and block.table is None:
                    raise IRValidationError(f"table block {block.block_id} has no table data")
        for section in self.sections:
            missing = [block_id for block_id in section.block_ids if block_id not in seen_blocks]
            if missing:
                raise IRValidationError(f"section {section.section_id} references unknown blocks: {missing[:3]}")
        return self

    # -- fingerprint -----------------------------------------------------
    def canonical_json(self, *, include_fingerprint: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_fingerprint=include_fingerprint),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def seal(self) -> DocumentIR:
        """Validate and stamp the canonical fingerprint (excludes the hash itself)."""
        self.page_count = len(self.pages)
        self.validate()
        self.fingerprint = self.compute_fingerprint()
        return self


def empty_ir(asset_id: str, parse_run_id: str, *, doc_type: str = "unknown") -> DocumentIR:
    return DocumentIR(
        document_id=asset_id,
        asset_id=asset_id,
        parse_run_id=parse_run_id,
        doc_type=doc_type,
        quality=QualityReport(status="failed", generation_allowed=False,
                              generation_block_reason="文档尚未解析"),
    )
