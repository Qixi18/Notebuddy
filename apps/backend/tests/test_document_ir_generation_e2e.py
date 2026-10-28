from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.database import Base
from app.db.models import Notebook, NotebookBlockSource, NotebookGenerationJob
from app.document_processing.service import create_parse_run, execute_parse_run
from app.notes.document import load_document
from app.schemas.generation import NotebookGenerationCreate
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import make_asset, make_course, make_notebook


def _write_text_pdf(path: Path) -> None:
    text = (
        b"BT /F1 20 Tf 50 740 Td (Chapter 1 Limits) Tj "
        b"/F1 12 Tf 0 -32 Td (A limit describes how a function approaches a value.) Tj "
        b"0 -24 Td (The notation is lim x to a, f of x equals L.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


@pytest.fixture()
def file_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'e2e.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_pdf_document_ir_flows_into_notebook_generation_with_source_citations(
    file_db, monkeypatch, tmp_path,
):
    from app.api.v1.generation import create_generation_job

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "notebook_generator", "offline-extractive")
    monkeypatch.setenv("NOTEBOOK_DOCUMENT_PARSER", "native")
    (tmp_path / "originals").mkdir()
    pdf_path = tmp_path / "originals" / "limits.pdf"
    _write_text_pdf(pdf_path)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(
        bind=file_db, autoflush=False, expire_on_commit=False,
    ))

    with Session(file_db, autoflush=False, expire_on_commit=False) as session:
        course = make_course(session)
        notebook = make_notebook(session, course)
        asset = make_asset(session, notebook, name="limits.pdf")
        asset.storage_key = "originals/limits.pdf"
        asset.byte_size = pdf_path.stat().st_size
        session.commit()

        parse_run = create_parse_run(session, asset=asset)
        parsed = execute_parse_run(session, parse_run.id, source_path=pdf_path)
        session.commit()
        assert parsed.run.status == "completed"
        assert parsed.ir.quality.generation_allowed is True
        assert "Chapter 1 Limits" in parsed.ir.pages[0].text

        created = create_generation_job(
            notebook.id, NotebookGenerationCreate(asset_ids=[asset.id]), "pdf-ir-e2e", session,
        )
        session.commit()
        assert worker.claim_next_generation_job() == created["id"]
        worker.process_generation_job(created["id"])

        session.expire_all()
        job = session.get(NotebookGenerationJob, created["id"])
        notebook = session.get(Notebook, notebook.id)
        assert job.status == "completed", job.error_message
        assert notebook.document_revision == 1
        content = load_document(notebook.document_json).content
        assert any("Limits" in str(node) for node in content["content"])
        citations = list(session.scalars(select(NotebookBlockSource).where(
            NotebookBlockSource.notebook_id == notebook.id,
        )).all())
        assert citations
        assert all(citation.parse_run_id == parsed.run.id for citation in citations)
