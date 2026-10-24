"""Format-independent parsing contracts used by the worker and evidence APIs."""

from __future__ import annotations

from dataclasses import dataclass, field

PARSER_VERSION = "phase2-1"


@dataclass(frozen=True)
class ParsedBlock:
    block_type: str
    content: str
    position: int
    object_id: str | None = None
    location_label: str | None = None
    font_size: float | None = None
    is_bold: bool = False
    extraction_method: str = "native_text"
    confidence: float | None = 1.0
    warning: str | None = None
    top: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    title: str | None
    raw_text: str
    location_type: str = "page"
    location_label: str | None = None
    stable_location_key: str = ""
    parse_status: str = "parsed"
    warning: str | None = None
    extraction_method: str = "native_text"
    confidence: float | None = 1.0
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    format: str
    parser_version: str
    pages: list[ParsedPage]
    material_id: str | None = None
    file_hash: str | None = None
    warnings: list[str] = field(default_factory=list)

