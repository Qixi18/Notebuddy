"""PDF text/layout extraction engines.

PyMuPDF is used when importable (layout, tables, page rendering); ``pypdf`` is
the text-only fallback so the pipeline still runs in a minimal install.

The engine returns *raw* geometry; converting it into IR blocks (headings,
paragraphs, tables, figures) is the adapter's job.  No engine writes business
data.
"""

from __future__ import annotations

import logging
from contextlib import closing
from io import BytesIO
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_RENDER_DPI = 130
MAX_RENDER_SIDE = 2400


@dataclass
class EngineInfo:
    name: str
    version: str
    available: bool
    capabilities: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "available": self.available,
            "capabilities": list(self.capabilities),
            "reason": self.reason,
        }


@dataclass
class RawSpan:
    text: str
    bbox: list[float] | None = None
    size: float | None = None
    bold: bool = False
    italic: bool = False
    font: str | None = None


@dataclass
class RawLine:
    spans: list[RawSpan] = field(default_factory=list)
    bbox: list[float] | None = None

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans).strip()


@dataclass
class RawTextBlock:
    lines: list[RawLine] = field(default_factory=list)
    bbox: list[float] | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text).strip()


@dataclass
class RawImageBlock:
    bbox: list[float] | None = None
    width: int | None = None
    height: int | None = None
    xref: int | None = None


@dataclass
class RawTable:
    rows: list[list[str]] = field(default_factory=list)
    bbox: list[float] | None = None


@dataclass
class RawPage:
    page_number: int
    width: float | None = None
    height: float | None = None
    rotation: int = 0
    text_blocks: list[RawTextBlock] = field(default_factory=list)
    image_blocks: list[RawImageBlock] = field(default_factory=list)
    tables: list[RawTable] = field(default_factory=list)
    text: str = ""
    render_png: bytes | None = None

    @property
    def has_text_layer(self) -> bool:
        return any(block.text for block in self.text_blocks)


@dataclass
class RawDocument:
    page_count: int
    pages: list[RawPage]
    engine: EngineInfo


def _pymupdf():
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except Exception:  # pragma: no cover - optional dependency
        return None


def availability() -> EngineInfo:
    module = _pymupdf()
    if module is not None:
        return EngineInfo(
            name="pymupdf", version=str(getattr(module, "__version__", "?")), available=True,
            capabilities=("text_layout", "tables", "images", "render", "ocr_hook"),
        )
    try:
        import pypdf  # type: ignore

        return EngineInfo(name="pypdf", version=str(getattr(pypdf, "__version__", "?")),
                          available=True, capabilities=("text_only",))
    except Exception as exc:  # pragma: no cover - dependency error
        return EngineInfo(name="none", version="0", available=False, reason=str(exc))


def _bbox(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    try:
        if hasattr(raw, "x0"):
            return [float(raw.x0), float(raw.y0), float(raw.x1), float(raw.y1)]
        values = list(raw)
        if len(values) == 4:
            return [float(item) for item in values]
    except (TypeError, ValueError):
        return None
    return None


def _render(page: Any, dpi: int) -> bytes | None:
    try:
        dpi = max(72, min(int(dpi), MAX_RENDER_DPI))
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        if max(pixmap.width, pixmap.height) > MAX_RENDER_SIDE:
            # Re-render at the reduced dpi instead of resampling the pixmap.
            scale = MAX_RENDER_SIDE / max(pixmap.width, pixmap.height)
            reduced = max(48, int(dpi * scale))
            pixmap = page.get_pixmap(dpi=reduced, alpha=False)
        return pixmap.tobytes("png")
    except Exception:  # pragma: no cover - rendering must not fail a parse
        logger.warning("Could not render PDF page", exc_info=True)
        return None


def extract_pdf(
    path: Path,
    *,
    render_when: Callable[[RawPage], bool] | None = None,
    render_dpi: int = 120,
) -> RawDocument:
    """Extract every page as raw geometry using the best available engine.

    ``render_when`` decides per page whether a PNG rendering is produced (used
    for OCR and for pages kept as visual evidence).  Text-only fallbacks never
    render.
    """

    module = _pymupdf()
    if module is not None:
        return _extract_with_pymupdf(module, path, render_when=render_when, render_dpi=render_dpi)
    return _extract_with_pypdf(path)


def extract_pdf_image(path: Path, xref: int) -> bytes | None:
    """Extract one embedded image by xref (used for optional figure vision)."""
    module = _pymupdf()
    if module is None:
        return None
    try:
        with module.open(str(path)) as document:
            payload = document.extract_image(xref)
            data = payload.get("image") if isinstance(payload, dict) else None
            return data if isinstance(data, (bytes, bytearray)) else None
    except Exception:  # pragma: no cover - optional enrichment
        logger.debug("Could not extract PDF image %s", xref, exc_info=True)
        return None


def render_pdf_page(path: Path, page_number: int, *, dpi: int = 120) -> bytes | None:
    """Render one source page, including in MinerU environments using PDFium."""
    if page_number < 1:
        return None
    module = _pymupdf()
    if module is not None:
        try:
            with module.open(str(path)) as document:
                if page_number > len(document):
                    return None
                rendered = _render(document[page_number - 1], dpi)
                if rendered:
                    return rendered
        except Exception:
            logger.debug("PyMuPDF source preview unavailable", exc_info=True)
    try:
        import pypdfium2 as pdfium

        with closing(pdfium.PdfDocument(str(path))) as document:
            if page_number > len(document):
                return None
            with closing(document[page_number - 1]) as page:
                width, height = page.get_size()
                scale = min(
                    max(72, min(int(dpi), MAX_RENDER_DPI)) / 72,
                    MAX_RENDER_SIDE / max(width, height, 1),
                )
                with closing(page.render(scale=scale)) as bitmap:
                    with bitmap.to_pil() as image:
                        output = BytesIO()
                        image.save(output, format="PNG")
                        return output.getvalue()
    except Exception:
        logger.debug("PDFium source preview unavailable", exc_info=True)
    return None


def _extract_with_pymupdf(
    module: Any,
    path: Path,
    *,
    render_when: Callable[[RawPage], bool] | None,
    render_dpi: int,
) -> RawDocument:
    pages: list[RawPage] = []
    with module.open(str(path)) as document:
        for index, page in enumerate(document, start=1):
            raw_page = RawPage(
                page_number=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                rotation=int(getattr(page, "rotation", 0) or 0),
            )
            try:
                payload = page.get_text("dict")
            except Exception:  # pragma: no cover
                payload = {"blocks": []}
            for block in payload.get("blocks") or []:
                block_type = block.get("type")
                bbox = _bbox(block.get("bbox"))
                if block_type == 0:
                    lines: list[RawLine] = []
                    for line in block.get("lines") or []:
                        spans = [
                            RawSpan(
                                text=str(span.get("text") or ""),
                                bbox=_bbox(span.get("bbox")),
                                size=float(span["size"]) if isinstance(span.get("size"), (int, float)) else None,
                                bold=bool(int(span.get("flags") or 0) & 16),
                                italic=bool(int(span.get("flags") or 0) & 2),
                                font=str(span.get("font")) if span.get("font") else None,
                            )
                            for span in line.get("spans") or []
                        ]
                        if any(span.text.strip() for span in spans):
                            lines.append(RawLine(spans=spans, bbox=_bbox(line.get("bbox"))))
                    if lines:
                        raw_page.text_blocks.append(RawTextBlock(lines=lines, bbox=bbox))
                elif block_type == 1:
                    raw_page.image_blocks.append(RawImageBlock(
                        bbox=bbox,
                        width=int(block["width"]) if isinstance(block.get("width"), (int, float)) else None,
                        height=int(block["height"]) if isinstance(block.get("height"), (int, float)) else None,
                        xref=int(block["xref"]) if isinstance(block.get("xref"), int) else None,
                    ))
            try:
                table_finder = getattr(page, "find_tables", None)
                if callable(table_finder):
                    found = table_finder()
                    for table in getattr(found, "tables", []) or []:
                        try:
                            rows = table.extract() or []
                        except Exception:  # pragma: no cover
                            rows = []
                        normalized = [
                            [(_cell if isinstance(_cell, str) else "" if _cell is None else str(_cell))
                             for _cell in row]
                            for row in rows if isinstance(row, list)
                        ]
                        if normalized and any(any(cell.strip() for cell in row) for row in normalized):
                            raw_page.tables.append(RawTable(rows=normalized, bbox=_bbox(table.bbox)))
            except Exception:  # pragma: no cover - optional table detection
                logger.debug("Table detection failed on page %s", index, exc_info=True)
            raw_page.text = "\n".join(block.text for block in raw_page.text_blocks if block.text).strip()
            if render_when is not None and render_when(raw_page):
                raw_page.render_png = _render(page, render_dpi)
            pages.append(raw_page)
    info = availability()
    return RawDocument(page_count=len(pages), pages=pages, engine=info)


def _extract_with_pypdf(path: Path) -> RawDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[RawPage] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # pragma: no cover
            text = ""
        raw_page = RawPage(page_number=index, text=text)
        try:
            box = page.mediabox
            raw_page.width = float(box.width)
            raw_page.height = float(box.height)
        except Exception:  # pragma: no cover
            logger.debug("pypdf page has no usable mediabox", exc_info=True)
        for paragraph in [part.strip() for part in text.split("\n\n") if part.strip()]:
            lines = [RawLine(spans=[RawSpan(text=line)]) for line in paragraph.splitlines() if line.strip()]
            if lines:
                raw_page.text_blocks.append(RawTextBlock(lines=lines))
        pages.append(raw_page)
    return RawDocument(
        page_count=len(pages), pages=pages,
        engine=EngineInfo(name="pypdf", version="text-only", available=True,
                          capabilities=("text_only",)),
    )
