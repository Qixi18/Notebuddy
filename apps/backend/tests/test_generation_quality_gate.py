from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import (
    Notebook,
    NotebookBlockSource,
    NotebookDocumentRevision,
    NotebookGenerationJob,
)
from app.generation.composer import Composition
from app.generation.quality_gate import inspect_generated_math
from app.notes.document import load_document, normalize_document, validate_document
from app.notes.store import write_document
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import make_asset, make_course, make_notebook, persist_ir


@pytest.fixture()
def file_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'quality-gate.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(file_db):
    with Session(file_db, autoflush=False, expire_on_commit=False) as session:
        yield session


def _doc_with_math(latex: str, *, node_type: str = "inlineMath") -> dict:
    node = {"type": node_type, "attrs": {"latex": latex}}
    if node_type == "blockMath":
        node["attrs"]["blockId"] = "math-block"
        content = [node]
    else:
        content = [{
            "type": "paragraph",
            "attrs": {"blockId": "prose-block"},
            "content": [{"type": "text", "text": "设 "}, node,
                        {"type": "text", "text": " 成立。"}],
        }]
    return {"type": "doc", "content": content}


def test_standard_inline_and_block_math_pass_structure_gate():
    formulas = [
        r"\mathbb{R}^n", r"x_k \to a",
        r"A=\{(x,y)\mid (x-x_0)^2+(y-y_0)^2<\delta^2\}",
        r"\|x_k-a\|<\varepsilon", r"U(a,\delta)=\{x\in\mathbb{R}^n\mid\|x-a\|<\delta\}",
        r"A^\circ", r"k\in\mathbb{N}_+", r"\frac{1}{2}mv^2", r"\sqrt{x^2+y^2}",
        r"\left(\frac{1}{2}\right)",
        r"\begin{aligned}a&=b+c\\&=d\end{aligned}",
        r"x \text{ 在中文句子中}",
    ]
    for latex in formulas:
        report = inspect_generated_math(_doc_with_math(latex))
        assert report.passed, (latex, report.issues)
        assert report.inline_math_count == 1
        assert report.elapsed_ms >= 0

    report = inspect_generated_math(_doc_with_math(r"\sum_{k=1}^n x_k", node_type="blockMath"))
    assert report.passed
    assert report.block_math_count == 1


def test_math_gate_blocks_malformed_and_untrusted_math_without_changing_symbols():
    cases = [
        ("", "invalid_inline_math"),
        (r"\frac{1}{2", "math_structure_invalid"),
        (r"(x+y", "math_structure_invalid"),
        (r"\left(x)", "math_structure_invalid"),
        (r"\begin{aligned}x&=y\end{array}", "math_structure_invalid"),
        (r"\(x+y\)", "math_delimiter_invalid"),
        (r"\href{https://example.test}{x}", "math_command_forbidden"),
        (r"\htmlClass{danger}{x}", "math_command_forbidden"),
        ("x" * 2_001, "invalid_inline_math"),
    ]
    for latex, expected_code in cases:
        report = inspect_generated_math(_doc_with_math(latex))
        assert not report.passed
        assert report.failure_codes == {expected_code: 1}
        assert report.issues[0].block_id == "prose-block"
        assert report.issues[0].node_path == "doc.content[0].content[1]"


def test_suspicious_text_math_is_diagnostic_and_ignores_code_and_filenames():
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockId": "p1"}, "content": [
                {"type": "text", "text": "矩阵元素 a_{ij} 满足条件。"},
                {"type": "text", "text": " 使用 "},
                {"type": "text", "text": "my_file.py", "marks": [{"type": "code"}]},
            ]},
            {"type": "codeBlock", "attrs": {"blockId": "code"}, "content": [
                {"type": "text", "text": "a_b = x^2"},
            ]},
        ],
    }
    report = inspect_generated_math(document)
    assert report.passed
    assert report.suspected_unstructured_math_count == 1
    assert report.issues[0].code == "suspected_unstructured_math"
    assert report.issues[0].severity == "diagnostic"


def test_invalid_generated_math_fails_before_document_revision_or_snapshot(
    db, file_db, monkeypatch,
):
    course = make_course(db)
    notebook = make_notebook(db, course)
    asset = make_asset(db, notebook)
    persist_ir(db, notebook, asset)
    db.commit()
    from app.api.v1.generation import create_generation_job
    from app.schemas.generation import NotebookGenerationCreate

    created = create_generation_job(
        notebook.id, NotebookGenerationCreate(asset_ids=[asset.id]), "invalid-math-gate", db,
    )
    job = db.get(NotebookGenerationJob, created["id"])
    snapshot = json.loads(job.input_snapshot_json)
    source_id = snapshot["sources"][0]["sections"][0]["blocks"][0]["block_id"]
    original_json = db.get(Notebook, notebook.id).document_json
    monkeypatch.setattr(worker, "compose", lambda *args, **kwargs: Composition(
        nodes=[{
            "type": "blockMath",
            "attrs": {"blockId": "bad-math", "latex": r"\frac{1}{2"},
        }],
        source_map={"bad-math": [source_id]},
    ))
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(
        bind=file_db, autoflush=False, expire_on_commit=False,
    ))
    assert worker.claim_next_generation_job() == created["id"]
    worker.process_generation_job(created["id"])

    db.expire_all()
    task = db.get(NotebookGenerationJob, created["id"])
    saved = db.get(Notebook, notebook.id)
    assert task.status == "failed"
    assert task.error_code == "math_structure_invalid"
    assert saved.document_json == original_json
    assert saved.document_revision == 0
    assert db.scalar(select(NotebookDocumentRevision)) is None


def test_valid_generated_math_appends_through_the_existing_source_and_revision_path(
    db, file_db, monkeypatch,
):
    course = make_course(db)
    notebook = make_notebook(db, course)
    asset = make_asset(db, notebook)
    persist_ir(db, notebook, asset)
    db.commit()
    from app.api.v1.generation import create_generation_job
    from app.schemas.generation import NotebookGenerationCreate

    created = create_generation_job(
        notebook.id, NotebookGenerationCreate(asset_ids=[asset.id]), "valid-math-gate", db,
    )
    job = db.get(NotebookGenerationJob, created["id"])
    snapshot = json.loads(job.input_snapshot_json)
    source_id = snapshot["sources"][0]["sections"][0]["blocks"][0]["block_id"]
    latex = r"\mathbb{R}^n"
    monkeypatch.setattr(worker, "compose", lambda *args, **kwargs: Composition(
        nodes=[{
            "type": "paragraph",
            "attrs": {"blockId": "valid-inline-math"},
            "content": [
                {"type": "text", "text": "函数定义在 "},
                {"type": "inlineMath", "attrs": {"latex": latex}},
            ],
        }],
        source_map={"valid-inline-math": [source_id]},
    ))
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(
        bind=file_db, autoflush=False, expire_on_commit=False,
    ))
    assert worker.claim_next_generation_job() == created["id"]
    worker.process_generation_job(created["id"])

    db.expire_all()
    task = db.get(NotebookGenerationJob, created["id"])
    saved = db.get(Notebook, notebook.id)
    content = load_document(saved.document_json).content
    paragraph = content["content"][0]
    math_node = paragraph["content"][1]
    sources = list(db.scalars(select(NotebookBlockSource).where(
        NotebookBlockSource.notebook_id == notebook.id,
    )))
    assert task.status == "completed", task.error_message
    assert saved.document_revision == 1
    assert math_node == {"type": "inlineMath", "attrs": {"latex": latex}}
    assert task.source_map_json == json.dumps({"valid-inline-math": [source_id]}, ensure_ascii=False)
    assert any(row.block_id == "valid-inline-math" and row.document_block_id for row in sources)


def test_user_can_save_an_in_progress_latex_node(db):
    course = make_course(db)
    notebook = make_notebook(db, course)
    partial = normalize_document({
        "type": "doc",
        "content": [{
            "type": "paragraph", "attrs": {"blockId": "user-math"},
            "content": [
                {"type": "text", "text": "正在输入："},
                {"type": "inlineMath", "attrs": {"latex": r"\frac{"}},
            ],
        }],
    })
    validate_document(partial)
    write_document(db, notebook, partial, expected_revision=0, origin="autosave")
    db.commit()

    db.refresh(notebook)
    assert notebook.document_revision == 1
    assert load_document(notebook.document_json).content == partial
