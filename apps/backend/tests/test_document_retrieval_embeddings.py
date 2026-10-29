import json
from types import SimpleNamespace

from sqlalchemy import select

from app.db.models import DocumentChunk
from app.document_processing.chunking import build_chunks
from app.document_processing.ir import BlockIR, DocumentIR, FigureData, PageIR, QualityReport
from app.document_processing.service import rebuild_views
from app.retrieval.index import embed_run_chunks
from app.retrieval.service import _retrieve_documents
from tests.notebook_fixtures import make_asset, make_course, make_notebook, persist_ir

pytest_plugins = ["tests.notebook_fixtures"]


def test_optional_embeddings_are_indexed_and_model_mismatches_fall_back_to_keyword(
    session, monkeypatch,
):
    course = make_course(session)
    notebook = make_notebook(session, course)
    asset = make_asset(session, notebook)
    run = persist_ir(session, notebook, asset)
    client = SimpleNamespace(configured=True, settings=SimpleNamespace(embedding_model="model-a"),
                             embed=lambda texts: [[1.0, 0.0] for _ in texts])
    result = embed_run_chunks(session, run.id, client=client)
    assert result["indexed"] > 0 and result["failed"] == 0
    chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.parse_run_id == run.id))
    assert json.loads(chunk.embedding_json) == [1.0, 0.0]
    monkeypatch.setattr("app.retrieval.service.settings_model", lambda: "model-a")
    kwargs = {"course_id": course.id, "terms": ["极限"], "query_vector": [1.0, 0.0],
              "material_id": None, "page_number": None}
    assert any(item.score_source == "hybrid" for item in _retrieve_documents(session, **kwargs))
    monkeypatch.setattr("app.retrieval.service.settings_model", lambda: "model-b")
    assert all(item.score_source == "keyword" for item in _retrieve_documents(session, **kwargs))
    kwargs["query_vector"] = [1.0, 0.0, 0.0]
    assert _retrieve_documents(session, **kwargs)


def test_failed_embedding_does_not_erase_existing_index(session):
    notebook = make_notebook(session, None)
    asset = make_asset(session, notebook)
    run = persist_ir(session, notebook, asset)
    chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.parse_run_id == run.id))
    chunk.embedding_json, chunk.embedding_model = "[1,0]", "old-model"
    client = SimpleNamespace(configured=True, settings=SimpleNamespace(embedding_model="new"),
                             embed=lambda texts: [[float("nan")] for _ in texts])
    result = embed_run_chunks(session, run.id, client=client)
    assert result["failed"] == result["total"] > 0
    assert chunk.embedding_json == "[1,0]" and chunk.embedding_model == "old-model"


def test_rebuilding_views_preserves_embeddings_for_unchanged_chunks(session):
    notebook = make_notebook(session, None)
    asset = make_asset(session, notebook)
    run = persist_ir(session, notebook, asset)
    rows = list(session.scalars(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run.id,
    ).order_by(DocumentChunk.order)))
    assert rows
    for index, row in enumerate(rows):
        row.embedding_json = json.dumps([float(index + 1), 0.0])
        row.embedding_model = "embedding-v1"
    expected = {row.text: row.embedding_json for row in rows}
    session.flush()

    rebuild_views(session, run.id)
    rebuilt = list(session.scalars(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run.id,
    )))

    assert {row.text: row.embedding_json for row in rebuilt} == expected
    assert all(row.embedding_model == "embedding-v1" for row in rebuilt)


def test_rebuilding_views_does_not_reuse_embedding_for_changed_text(session):
    from app.db.models import DocumentBlock

    notebook = make_notebook(session, None)
    asset = make_asset(session, notebook)
    run = persist_ir(session, notebook, asset)
    old_chunk = session.scalar(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run.id,
    ).order_by(DocumentChunk.order))
    old_chunk.embedding_json, old_chunk.embedding_model = "[1,0]", "embedding-v1"
    block_id = json.loads(old_chunk.block_ids_json)[0]
    block = session.scalar(select(DocumentBlock).where(
        DocumentBlock.parse_run_id == run.id, DocumentBlock.block_id == block_id,
    ))
    block.text = "完全不同的新内容，旧语义向量不能复用。" * 8
    session.flush()

    rebuild_views(session, run.id)
    rebuilt = list(session.scalars(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run.id,
    )))

    assert all(row.embedding_json is None for row in rebuilt)


def test_short_equation_and_unexplained_image_have_traceable_chunks():
    def document(block):
        return DocumentIR(
            document_id="doc", asset_id="asset", parse_run_id="run", doc_type="pdf",
            page_count=1, quality=QualityReport(status="partial"),
            pages=[PageIR(page_id="logical-page-7", page_number=7, blocks=[block])],
        )

    equation = BlockIR(block_id="eq-short", page_number=7, order=0, global_order=0,
                       type="equation", latex="E=mc^2", text="", extraction="mineru")
    figure = BlockIR(block_id="visual-raw", page_number=7, order=0, global_order=0,
                     type="figure", figure=FigureData(image_key="derived/diagram.png"),
                     extraction="mineru")

    equation_chunks = build_chunks(document(equation))
    visual_chunks = build_chunks(document(figure))

    assert len(equation_chunks) == 1
    assert "E=mc^2" in equation_chunks[0].text
    assert equation_chunks[0].block_ids == ["eq-short"]
    assert equation_chunks[0].page_numbers == [7]
    assert len(visual_chunks) == 1
    assert "未解读图像证据" in visual_chunks[0].text
    assert visual_chunks[0].block_ids == ["visual-raw"]
    assert visual_chunks[0].page_numbers == [7]
