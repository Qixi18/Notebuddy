"""PDF text/layout extraction engines.

PyMuPDF is used when importable (layout, tables, page rendering); ``pypdf`` is
the text-only fallback so the pipeline still runs in a minimal install.

The engine returns *raw* geometry; converting it into IR blocks (headings,
paragraphs, tables, figures) is the adapter's job.  No engine writes business
data.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from io import BytesIO
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
    superscript: bool = False


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
    is_vector: bool = False


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
    render_error: str | None = None
    has_vector_content: bool = False

    @property
    def has_text_layer(self) -> bool:
        return any(block.text for block in self.text_blocks)

    @property
    def requires_ocr(self) -> bool:
        if not self.has_text_layer:
            return True
        area = (self.width or 0) * (self.height or 0)
        if not area:
            return False
        from app.document_processing.normalization.layout import covered_area

        boxes = [[max(0, image.bbox[0]), max(0, image.bbox[1]),
                  min(self.width, image.bbox[2]), min(self.height, image.bbox[3])]
                 for image in self.image_blocks if not image.is_vector and image.bbox]
        boxes = [box for box in boxes if box[2] > box[0] and box[3] > box[1]]
        if covered_area(boxes) / area < .6:
            return False
        chars = sum(len(block.text.strip()) for block in self.text_blocks)
        inside = sum(len(block.text.strip()) for block in self.text_blocks if block.bbox
                     and any(box[0] <= (block.bbox[0] + block.bbox[2]) / 2 <= box[2]
                             and box[1] <= (block.bbox[1] + block.bbox[3]) / 2 <= box[3]
                             for box in boxes))
        return chars < 80 or inside < chars * .1


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
        capabilities = ["text_only"]
        version = str(getattr(pypdf, "__version__", "?"))
        try:
            import pypdfium2  # type: ignore

            version = str(getattr(pypdfium2, "__version__", version))
            capabilities.append("render")
        except Exception:
            version = "?"
        return EngineInfo(name="pypdf+pdfium" if "render" in capabilities else "pypdf",
                          version=version, available=True, capabilities=tuple(capabilities))
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


def _render(page: Any, dpi: int, *, clip: Any = None) -> bytes | None:
    try:
        dpi = max(72, min(int(dpi), MAX_RENDER_DPI))
        rect = clip if clip is not None else page.rect
        max_dpi = int(72 * MAX_RENDER_SIDE / max(rect.width, rect.height, 1))
        if max_dpi < 1:
            logger.warning("PDF geometry exceeds the bounded renderer's supported size")
            return None
        dpi = min(dpi, max_dpi)
        kwargs = {"dpi": dpi, "alpha": False}
        if clip is not None:
            kwargs["clip"] = clip
        pixmap = page.get_pixmap(**kwargs)
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
    for OCR and for pages kept as visual evidence). PDFium supplies rendering
    when PyMuPDF is not installed, so text-only extraction never silently
    disables native OCR.
    """

    pages = list(iter_pdf_pages(path, render_when=render_when, render_dpi=render_dpi))
    return RawDocument(page_count=len(pages), pages=pages, engine=availability())


def iter_pdf_pages(path: Path, *, render_when: Callable[[RawPage], bool] | None = None,
                   render_dpi: int = 120, page_numbers: list[int] | None = None) -> Iterator[RawPage]:
    """Release each raw page/render after the consumer has persisted its evidence."""
    module = _pymupdf()
    if module is not None:
        yield from _iter_with_pymupdf(module, path, render_when=render_when, render_dpi=render_dpi,
                                      page_numbers=page_numbers)
    else:
        yield from _iter_with_pypdf(path, render_when=render_when, render_dpi=render_dpi,
                                   page_numbers=page_numbers)


def render_pdf_region(path: Path, page_number: int, bbox: list[float]) -> bytes | None:
    module = _pymupdf()
    if module is None:
        return None
    try:
        with module.open(str(path)) as document:
            page = document[page_number - 1]
            rect = module.Rect(bbox) & page.rect
            return _render(page, 120, clip=rect) if not rect.is_empty else None
    except Exception:
        logger.debug("Could not render vector evidence", exc_info=True)
        return None


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
                with closing(page.render(scale=scale)) as bitmap, bitmap.to_pil() as image:
                    output = BytesIO()
                    image.save(output, format="PNG")
                    return output.getvalue()
    except Exception:
        logger.debug("PDFium source preview unavailable", exc_info=True)
    return None


def _iter_with_pymupdf(
    module: Any,
    path: Path,
    *,
    render_when: Callable[[RawPage], bool] | None,
    render_dpi: int,
    page_numbers: list[int] | None = None,
) -> Iterator[RawPage]:
    with module.open(str(path)) as document:
        for index, page in enumerate(document, start=1):
            if page_numbers is not None and index not in page_numbers:
                continue
            raw_page = RawPage(
                page_number=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                rotation=int(getattr(page, "rotation", 0) or 0),
            )
            try:
                # Images are located through xrefs below; avoid copying every
                # embedded image's bytes into the text-layout dictionary.
                payload = page.get_text("dict", flags=module.TEXTFLAGS_DICT & ~module.TEXT_PRESERVE_IMAGES)
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
                                superscript=bool(int(span.get("flags") or 0) & 1),
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
            _attach_image_xrefs(page, raw_page)
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
            from app.document_processing.normalization.layout import order_text_blocks

            raw_page.text_blocks = order_text_blocks(raw_page.text_blocks, raw_page.width or 1)
            _attach_vectors(page, raw_page)
            raw_page.text = "\n".join(block.text for block in raw_page.text_blocks if block.text).strip()
            if render_when is not None and render_when(raw_page):
                raw_page.render_png = _render(page, render_dpi)
                if raw_page.render_png is None:
                    raw_page.render_error = f"第 {index} 页 PyMuPDF 渲染失败"
            yield raw_page


def _attach_vectors(page: Any, raw_page: RawPage) -> None:
    try:
        raw_page.has_vector_content = bool(page.get_drawings())
    except Exception:
        raw_page.has_vector_content = True  # Unknown geometry is unsafe for the strict router.
    try:
        regions = page.cluster_drawings()
    except Exception:
        return
    for region in regions:
        box = _bbox(region)
        if not box or (box[2] - box[0]) * (box[3] - box[1]) < 400:
            continue
        if any(table.bbox and table.bbox[0] - 3 <= box[0] and table.bbox[1] - 3 <= box[1]
               and table.bbox[2] + 3 >= box[2] and table.bbox[3] + 3 >= box[3]
               for table in raw_page.tables):
            continue
        raw_page.image_blocks.append(RawImageBlock(bbox=box, is_vector=True))


def _attach_image_xrefs(page: Any, raw_page: RawPage) -> None:
    """Recover image xrefs when the text-dict API omits them."""
    try:
        image_refs = page.get_images(full=True)
    except Exception:  # pragma: no cover - optional API differs by PyMuPDF version
        return
    for image_ref in image_refs or []:
        try:
            xref = int(image_ref[0])
            rects = page.get_image_rects(xref)
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        for rect in rects or []:
            rect_bbox = _bbox(rect)
            if rect_bbox is None:
                continue
            matched = next((
                image for image in raw_page.image_blocks
                if image.xref is None and image.bbox is not None
                and all(abs(left - right) <= 1.0 for left, right in zip(image.bbox, rect_bbox))
            ), None)
            if matched is not None:
                matched.xref = xref
            elif not any(
                image.xref == xref and image.bbox is not None
                and all(abs(left - right) <= 1.0 for left, right in zip(image.bbox, rect_bbox))
                for image in raw_page.image_blocks
            ):
                raw_page.image_blocks.append(RawImageBlock(bbox=rect_bbox, xref=xref))


def _iter_with_pypdf(
    path: Path,
    *,
    render_when: Callable[[RawPage], bool] | None = None,
    render_dpi: int = 120,
    page_numbers: list[int] | None = None,
) -> Iterator[RawPage]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pdfium_document = None
    render_error = None
    if render_when is not None:
        try:
            import pypdfium2 as pdfium

            pdfium_document = pdfium.PdfDocument(str(path))
        except Exception as exc:
            render_error = f"PDFium 无法打开 PDF：{type(exc).__name__}: {exc}"
            logger.warning("PDFium could not open PDF for page rendering", exc_info=True)
    try:
        for index, page in enumerate(reader.pages, start=1):
            if page_numbers is not None and index not in page_numbers:
                continue
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:  # pragma: no cover
                text = ""
                page_error = f"第 {index} 页文字层读取失败：{type(exc).__name__}"
            else:
                page_error = None
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
            if len(text.strip()) < 80:
                try:
                    objects = page.get("/Resources", {}).get("/XObject", {})
                    if hasattr(objects, "get_object"):
                        objects = objects.get_object()
                    if any(value.get_object().get("/Subtype") == "/Image" for value in objects.values()):
                        raw_page.image_blocks.append(RawImageBlock(
                            bbox=[0, 0, raw_page.width or 1, raw_page.height or 1]))
                except Exception:
                    logger.debug("Could not inspect fallback image objects", exc_info=True)
            if page_error:
                raw_page.render_error = page_error
            elif render_when is not None and render_when(raw_page):
                if pdfium_document is None:
                    raw_page.render_error = render_error or "PDFium 不可用，无法渲染扫描页"
                elif index > len(pdfium_document):
                    raw_page.render_error = f"PDFium 缺少第 {index} 页，无法渲染"
                else:
                    try:
                        with closing(pdfium_document[index - 1]) as pdfium_page:
                            width, height = pdfium_page.get_size()
                            scale = min(
                                max(72, min(int(render_dpi), MAX_RENDER_DPI)) / 72,
                                MAX_RENDER_SIDE / max(width, height, 1),
                            )
                            with closing(pdfium_page.render(scale=scale)) as bitmap, bitmap.to_pil() as image:
                                output = BytesIO()
                                image.save(output, format="PNG")
                                raw_page.render_png = output.getvalue()
                    except Exception as exc:
                        raw_page.render_error = (
                            f"第 {index} 页 PDFium 渲染失败：{type(exc).__name__}: {exc}"
                        )
            yield raw_page
    finally:
        if pdfium_document is not None:
            pdfium_document.close()
