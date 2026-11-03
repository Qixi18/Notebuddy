"""Route selection and bounded, resumable curriculum processing."""
from __future__ import annotations

import json
from contextlib import contextmanager
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select

from app.ai.deepseek import DeepSeekError
from app.core.config import settings
from app.db.database import get_db
from app.db.models import CurriculumImport, ForestJob
from app.document_processing.checkpoints import WorkPending
from app.forest import curriculum_reading
from app.forest.curriculum import create_import, extract_curriculum
from app.forest.curriculum_processing import CurriculumProcessingError
from app.main import app

pytest_plugins = ["tests.notebook_fixtures"]


@pytest.fixture
def client(session, monkeypatch):
    def database():
        yield session
    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    return TestClient(app)


def test_import_uses_saved_route_and_freezes_non_secret_provider_identity(client, session, monkeypatch):
    monkeypatch.setattr(settings, "document_processing_route", "llm")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "deepseek_model", "first-model")
    response = client.post("/api/v1/forest/curriculum-imports", data={"text": "Course | 1"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body.get("processing_route") == "llm"
    job = session.get(ForestJob, body["job_id"])
    snapshot = json.loads(job.source_snapshot_json)
    assert snapshot["provider"]["model"] == "first-model"
    assert "test-key" not in job.source_snapshot_json
    record = session.get(CurriculumImport, body["id"])
    record.status = job.status = "failed"
    session.commit()
    monkeypatch.setattr(settings, "document_processing_route", "standard")
    monkeypatch.setattr(settings, "deepseek_model", "second-model")
    retried = client.post(f"/api/v1/forest/curriculum-imports/{record.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["processing_route"] == "llm"
    assert json.loads(job.source_snapshot_json)["provider"]["model"] == "first-model"


def test_single_import_can_override_default_route(client, monkeypatch):
    monkeypatch.setattr(settings, "document_processing_route", "llm")
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    response = client.post("/api/v1/forest/curriculum-imports",
                           data={"text": "Course | 1", "processing_route": "standard"})
    assert response.status_code == 201
    assert response.json().get("processing_route") == "standard"


def test_llm_route_without_model_configuration_is_rejected_before_enqueue(client, session, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    response = client.post("/api/v1/forest/curriculum-imports",
                           data={"text": "Course | 1", "processing_route": "llm"})
    assert response.status_code == 422
    assert session.scalar(select(ForestJob)) is None


class CurriculumModel:
    configured = True
    last_usage = None
    last_finish_reason = None

    def __init__(self, fail_page=None):
        self.reads = []
        self.batches = []
        self.fail_page = fail_page

    def complete_json(self, messages, *, max_tokens, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, list):
            import re
            number = int(re.search(r"\d+", content[0]["text"]).group())
            self.reads.append(number)
            if self.fail_page == number:
                self.fail_page = None
                raise DeepSeekError("Synthetic provider failure", code="authentication_failed")
            return {"status": "read", "blocks": [{"type": "table", "text": "", "rows": [
                ["course name", "semester", "level"], [f"Course {number}", str(number), "foundation"],
            ]}]}
        units = json.loads(content)
        self.batches.append(units)
        return {"rows": [{"key": unit["key"], "name": unit["source_excerpt"].split("|")[0].strip(),
                          "semester": 1, "level": "foundation", "prerequisites": []}
                         for unit in units if "course name" not in unit["source_excerpt"].casefold()]}


def scanned_import(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    writer = PdfWriter()
    writer.add_blank_page(300, 400)
    writer.add_blank_page(300, 400)
    source = BytesIO()
    writer.write(source)
    source.seek(0)
    record = create_import(session, text=None, source=source, filename="scanned.pdf",
                           processing_route="llm")

    @contextmanager
    def pages(*args, **kwargs):
        yield 2, lambda number: b"synthetic-page-image"
    monkeypatch.setattr(curriculum_reading.rendering, "page_images", pages)
    return record


def test_scanned_pdf_uses_shared_page_reader_and_reuses_successful_pages_after_failure(session, tmp_path, monkeypatch):
    record = scanned_import(session, tmp_path, monkeypatch)
    model = CurriculumModel(fail_page=2)
    with pytest.raises(DeepSeekError):
        extract_curriculum(session, record, client=model)
    session.rollback()
    extract_curriculum(session, record, client=model)
    assert model.reads == [1, 2, 2]
    assert len(json.loads(record.rows_json)) == 2
    assert record.status == "preview"


def test_long_text_is_extracted_in_bounded_batches_and_reuses_them(session, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    text = "course name | semester | level\n" + "\n".join(
        f"Course {index} | 1 | foundation" for index in range(100))
    record = create_import(session, text=text, processing_route="llm")
    model = CurriculumModel()
    extract_curriculum(session, record, client=model)
    assert len(model.batches) > 1
    assert all(len(batch) <= 40 for batch in model.batches)
    assert len(json.loads(record.rows_json)) == 100
    requests = len(model.batches)
    extract_curriculum(session, record, client=model)
    assert len(model.batches) == requests


def test_cooperative_yield_keeps_successful_steps_and_checks_source_on_resume(session, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    record = create_import(session, text="\n".join(f"Course {n} | 1" for n in range(90)))
    model = CurriculumModel()
    with pytest.raises(WorkPending):
        extract_curriculum(session, record, client=model, max_new_steps=1)
    session.rollback()
    assert len(model.batches) == 1
    assert record.status == "pending"
    extract_curriculum(session, record, client=model)
    assert len(model.batches) == 3
    record.input_text += "\nCourse changed | 2"
    with pytest.raises(CurriculumProcessingError, match="已变化"):
        extract_curriculum(session, record, client=model)
    assert len(model.batches) == 3


def test_invalid_model_evidence_is_not_cached(session, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    record = create_import(session, text="Course A | 1")
    model = CurriculumModel()
    original = model.complete_json
    model.complete_json = lambda *a, **k: {"rows": [{"key": "source-1", "name": "Invented"}]}
    from app.forest.curriculum import CurriculumError
    with pytest.raises(CurriculumError, match="依据"):
        extract_curriculum(session, record, client=model)
    model.complete_json = original
    extract_curriculum(session, record, client=model)
    assert len(model.batches) == 1
    assert json.loads(record.rows_json)[0]["name"] == "Course A"


def test_worker_yields_and_resumes_to_preview_without_decreasing_progress(session, engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.forest import jobs
    from app.forest.curriculum_processing import CurriculumRun
    monkeypatch.setattr(jobs, 'SessionLocal', sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')
    model = CurriculumModel()
    init = CurriculumRun.__init__
    def injected(self, *args, **kwargs):
        kwargs['client'] = model
        init(self, *args, **kwargs)
    monkeypatch.setattr(CurriculumRun, '__init__', injected)
    record = create_import(session, text='\n'.join(f'Course {n} | 1' for n in range(160)))
    job_id = jobs.claim_next_forest_job()
    jobs.process_forest_job(job_id)
    session.expire_all()
    job = session.get(ForestJob, job_id)
    assert job.status == 'pending'
    progress = job.progress
    assert progress > 55
    assert record.status == 'pending'
    assert jobs.claim_next_forest_job() == job_id
    jobs.process_forest_job(job_id)
    session.expire_all()
    assert job.status == 'completed' and job.progress == 100
    assert record.status == 'preview'
    assert len(model.batches) == 4


def test_model_cannot_invent_credits_from_other_numeric_columns(session, monkeypatch):
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')
    record = create_import(session, text='课程名称 | 学期\n数学 | 4')
    model = CurriculumModel()
    model.complete_json = lambda *a, **k: {'rows': [{'key': 'source-2', 'name': '数学', 'credits': 4}]}
    from app.forest.curriculum import CurriculumError
    with pytest.raises(CurriculumError, match='学分'):
        extract_curriculum(session, record, client=model)


def test_unreadable_vision_page_has_actionable_error_and_no_preview(session, tmp_path, monkeypatch):
    record = scanned_import(session, tmp_path, monkeypatch)
    model = CurriculumModel()
    model.complete_json = lambda *a, **k: {'status': 'unreadable', 'blocks': []}
    with pytest.raises(CurriculumProcessingError, match='第 1 页'):
        extract_curriculum(session, record, client=model)
    assert record.status != 'preview'


def test_semester_and_category_headings_survive_multiple_extraction_batches(session, monkeypatch):
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-key')
    record = create_import(session, text='Semester 3\nFoundation\ncourse name | credits\n' + '\n'.join(f'Course {n} | 4' for n in range(45)))
    model = CurriculumModel()
    original = model.complete_json
    def without_inference(*args, **kwargs):
        result = original(*args, **kwargs)
        for row in result['rows']:
            row['semester'] = None
            row['level'] = 'unspecified'
        result['rows'] = [row for row in result['rows'] if row['name'].startswith('Course ')]
        return result
    model.complete_json = without_inference
    extract_curriculum(session, record, client=model)
    assert len(model.batches) == 2
    rows = json.loads(record.rows_json)
    assert len(rows) == 45
    assert all(row['semester'] == 3 and row['level'] == 'foundation' for row in rows)
    assert all(unit.get('heading_context') for unit in model.batches[1])


def test_continued_table_retains_verifiable_header_and_accepts_its_metadata(session, tmp_path, monkeypatch):
    from app.forest.curriculum import _source_units, _validate_extracted
    from app.parsers.base import ParsedBlock, ParsedDocument, ParsedPage
    record = scanned_import(session, tmp_path, monkeypatch)
    document = ParsedDocument(format='pdf', parser_version='test', pages=[
        ParsedPage(page_number=1, title=None, raw_text='', blocks=[ParsedBlock(block_type='table', position=0, content='课程代码 | 课程名称 | 学分 | 学时 | 性质\nM01 | 数学 | 4 | 64 | 必修')]),
        ParsedPage(page_number=2, title=None, raw_text='', blocks=[ParsedBlock(block_type='table', position=0, content='E01 | 英语 | 2 | 32 | 选修')]),
    ])
    units, warnings = _source_units(record, document=document)
    result = _validate_extracted({'rows': [{'key': units[-1]['key'], 'name': '英语', 'course_code': 'E01', 'credits': 2, 'hours': 32, 'requirement': 'elective'}]}, units)
    assert result['rows'][0]['credits'] == 2
    assert units[-1]['table_header_source']
    assert any('续表' in message for message in warnings)


def test_code_must_be_from_a_code_column_or_label():
    from app.forest.curriculum import CurriculumError, _validate_extracted
    with pytest.raises(CurriculumError, match='代码'):
        _validate_extracted({'rows': [{'key': 'a', 'name': 'Math', 'course_code': '4'}]}, [
            {'key': 'a', 'source_excerpt': 'Math | 4', 'table_header': ['course name', 'semester']},
        ])


def test_explicit_labeled_metadata_is_valid_evidence():
    from app.forest.curriculum import _validate_extracted
    result = _validate_extracted({'rows': [{'key': 'a', 'name': 'Math', 'course_code': 'M01', 'credits': 4, 'hours': 64, 'requirement': 'required'}]}, [
        {'key': 'a', 'source_excerpt': 'Course: Math | code: M01 | credits: 4 | hours: 64 | required', 'table_header': None},
    ])
    assert result['rows'][0]['course_code'] == 'M01'
