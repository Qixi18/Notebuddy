from app.document_processing.engines.pdf_text import EngineInfo
from app.document_processing.ir import BlockIR, DocumentIR, FigureData, PageIR, TableData
from app.document_processing.quality import EngineState, assess

ENGINES = EngineState(
    ocr=EngineInfo(name="test", version="1", available=True),
    vision=EngineInfo(name="test", version="1", available=True),
)


def _document(*pages: PageIR, doc_type: str = "image") -> DocumentIR:
    return DocumentIR(
        document_id="asset-1", asset_id="asset-1", parse_run_id="run-1",
        doc_type=doc_type, page_count=len(pages), pages=list(pages),
    )


def _page(number: int, text: str, *, status: str = "parsed", blocks=None, confidence=None):
    return PageIR(
        page_id=f"p{number}", page_number=number, status=status, text=text,
        blocks=list(blocks or []), confidence=confidence,
    )


def test_short_but_meaningful_image_text_is_allowed():
    report = assess(_document(_page(1, "x=1")), engines=ENGINES, doc_type="image")

    assert report.status == "complete"
    assert report.text_chars == 3
    assert report.generation_allowed is True


def test_structured_short_formula_and_table_are_usable():
    equation = BlockIR(
        block_id="eq-1", page_number=1, order=0, global_order=0,
        type="equation", text="x=1", latex="x=1",
    )
    table = BlockIR(
        block_id="table-1", page_number=1, order=1, global_order=1,
        type="table", text="x | 1", table=TableData(rows=[["x", "1"]]),
    )
    report = assess(
        _document(_page(1, "", blocks=[equation, table])),
        engines=ENGINES, doc_type="image",
    )

    assert report.pages_ok == 1
    assert report.generation_allowed is True


def test_unrecognized_image_placeholder_is_not_usable():
    image = BlockIR(
        block_id="img-1", page_number=1, order=0, global_order=0,
        type="image", text="原始图片（未识别文字）",
        figure=FigureData(kind="other", uncertain=True),
    )
    report = assess(
        _document(_page(1, "原始图片（未识别文字）", status="needs_ocr", blocks=[image])),
        engines=ENGINES, doc_type="image",
    )

    assert report.generation_allowed is False
    assert report.pages_ok == 0
    assert any(issue.code == "ocr_required" and issue.severity == "blocking"
               for issue in report.issues)


def test_blocking_page_prevents_generation_even_with_other_usable_pages():
    report = assess(
        _document(_page(1, "有效短内容"), _page(2, "", status="failed"), doc_type="pdf"),
        engines=ENGINES, doc_type="pdf",
    )

    assert report.status == "partial"
    assert report.generation_allowed is False
    assert report.pages_failed == 1
    assert any(issue.code == "page_failed" and issue.severity == "blocking"
               for issue in report.issues)


def test_empty_pages_are_reported_as_partial_not_silently_complete():
    report = assess(
        _document(_page(1, "有效内容"), _page(2, "", status="empty"), doc_type="pdf"),
        engines=ENGINES, doc_type="pdf",
    )

    assert report.status == "partial"
    assert report.generation_allowed is True
    assert any(issue.code == "empty_pages" and issue.page_numbers == [2]
               for issue in report.issues)
