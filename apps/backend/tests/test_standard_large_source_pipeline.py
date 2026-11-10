"""Large synthetic PDF through the real upload, parser, persistence and body writer."""
from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentBlock, NotebookBlockSource, NotebookGenerationJob
from app.document_processing.service import current_run, load_ir
from app.main import app
from tests.test_notebook_workspace import _create_course_and_book, _run_until_generation, _upload

pytest_plugins = ["tests.test_notebook_workspace"]


def test_six_hundred_page_pdf_preserves_body_tail_and_exact_source_rows(env, monkeypatch):
    engine, _factory, tmp_path = env
    monkeypatch.setattr(settings, "notebook_generator", "offline-extractive")
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "native")
    monkeypatch.setenv("NOTEBOOK_OCR_ENGINE", "none")
    path = tmp_path / "large-standard.pdf"
    with pymupdf.open() as pdf:
        for number in range(600):
            text = (f"Limit source page {number}. "
                    + "A limit describes how a function approaches a specified value. " * 8
                    + f"PAGE_MARKER_{number}.")
            if number == 599:
                text += " UNIQUE_DOCUMENT_TAIL."
            remaining = pdf.new_page().insert_textbox(
                pymupdf.Rect(40, 60, 550, 760), text, fontsize=10)
            assert remaining >= 0, "synthetic page text did not fit"
        pdf.save(path)
    with TestClient(app) as client:
        course_id, notebook_id = _create_course_and_book(client)
        uploaded = _upload(client, notebook_id, path.read_bytes(), name=path.name)
        _run_until_generation(engine)
        response = client.get(f"/api/v1/courses/{course_id}/notebooks/{notebook_id}/document")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["revision"] == 1
        assert "UNIQUE_DOCUMENT_TAIL" in str(body["content"])
        with Session(engine) as db:
            job = db.scalar(select(NotebookGenerationJob))
            assert job.status == "completed", job.error_message
            run = current_run(db, uploaded["asset"]["id"])
            document = load_ir(db, run)
            assert len(document.pages) == 600
            for number in range(600):
                assert f"PAGE_MARKER_{number}" in document.pages[number].text
                assert f"PAGE_MARKER_{number}" in str(body["content"])
            source_ids = set(db.scalars(select(DocumentBlock.id).where(
                DocumentBlock.parse_run_id == run.id)).all())
            cited_ids = set(db.scalars(select(NotebookBlockSource.document_block_id).where(
                NotebookBlockSource.notebook_id == notebook_id)).all())
            assert cited_ids == source_ids
