import json
from types import SimpleNamespace

from sqlalchemy import select

from app.db.models import DocumentChunk
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
