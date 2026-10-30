"""Model-only reading keeps evidence and resumes only identical successful pages."""
from __future__ import annotations

import json

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.core.config import settings
from app.db.models import ProcessingStep
from app.document_processing import service
from tests.notebook_fixtures import make_asset, make_course, make_notebook

pytest_plugins = ['tests.notebook_fixtures']


def setup_pdf(db, tmp_path, pages=2):
    book = make_notebook(db, make_course(db))
    asset = make_asset(db, book, name='pages.pdf')
    asset.processing_route = 'llm'
    asset.processing_config_json = json.dumps({'model': 'vision-test', 'base_url': 'https://example.test'})
    path = tmp_path / 'pages.pdf'
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    writer.write(path)
    db.commit()
    return asset, path


def page_result(text='Visual source content for a useful learning note.'):
    return {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': text}]}


def test_null_block_levels_preserve_page_content_and_checkpoint(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path, pages=1)
    result = {'status': 'read', 'blocks': [
        {'type': 'heading', 'text': 'Matrix operations', 'level': 2},
        {'type': 'paragraph', 'text': 'Multiplication combines compatible matrices.', 'level': None},
        {'type': 'equation', 'text': '', 'latex': 'AB=C', 'level': None},
        {'type': 'table', 'text': '', 'rows': [['A', 'B'], ['2', '3']], 'level': None},
    ]}
    from app.ai.deepseek import DeepSeekClient
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k: result)
    run = service.create_parse_run(session, asset=asset)
    outcome = service.execute_parse_run(session, run.id, source_path=path)
    blocks = outcome.ir.pages[0].blocks
    assert [block.level for block in blocks] == [2, 0, 0, 0]
    assert blocks[1].text == result['blocks'][1]['text']
    assert blocks[2].latex == 'AB=C'
    assert blocks[3].table.rows == [['A', 'B'], ['2', '3']]
    checkpoint = session.scalar(select(ProcessingStep).where(ProcessingStep.scope == asset.id))
    assert [block['level'] for block in json.loads(checkpoint.result_json)['blocks']] == [2, 0, 0, 0]


@pytest.mark.parametrize('level', [-1, 7, 'invalid'])
def test_invalid_block_levels_still_fail(level):
    from pydantic import ValidationError

    from app.document_processing.llm_reader import ReadPage
    result = page_result()
    result['blocks'][0]['level'] = level
    with pytest.raises(ValidationError):
        ReadPage.model_validate(result)


def test_page_reader_accepts_irrelevant_metadata_and_null_optional_fields():
    from app.document_processing.llm_reader import _validate_page
    page = _validate_page({'status': 'read', 'confidence': 0.9, 'blocks': [{
        'type': 'equation', 'text': None, 'latex': 'AB=C', 'level': None,
        'uncertain': None, 'font_size': 18,
    }]}, 18)
    block = page.blocks[0]
    assert block.latex == 'AB=C'
    assert block.text == ''
    assert block.level == 0
    assert block.uncertain is False


def test_page_reader_still_rejects_blocks_without_source_content():
    from app.document_processing.llm_reader import _validate_page
    with pytest.raises(ValueError, match='无效内容块'):
        _validate_page({'status': 'read', 'blocks': [{'type': 'paragraph', 'text': None}]}, 18)


def test_llm_route_reads_images_without_local_semantic_parser(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path)
    def no_native(*args, **kwargs):
        pytest.fail('The model-only route invoked a local text/OCR parser')
    monkeypatch.setattr(service, 'parse_pdf', no_native)
    monkeypatch.setattr(service, 'engine_state', no_native)
    from app.ai.deepseek import DeepSeekClient
    def answer(self, messages, **kwargs):
        images = messages[-1]['content']
        assert any(part.get('type') == 'image_url' for part in images)
        return page_result()
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    run = service.create_parse_run(session, asset=asset)
    outcome = service.execute_parse_run(session, run.id, source_path=path)
    session.commit()
    assert outcome.run.parser_name == 'llm-vision'
    assert outcome.ir.page_count == 2
    assert outcome.ir.quality.generation_allowed
    assert all(page.render_key for page in outcome.ir.pages)
    assert all(block.extraction == 'vision' for block in outcome.ir.all_blocks())


def test_failed_later_page_reuses_successful_page_on_retry(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path)
    from app.ai.deepseek import DeepSeekClient, DeepSeekError
    outputs = iter([page_result('Page one has a real source.'), DeepSeekError('Unauthorized', status_code=401)])
    def fail_later(self, *args, **kwargs):
        result = next(outputs)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(DeepSeekClient, 'complete_json', fail_later)
    first = service.create_parse_run(session, asset=asset)
    with pytest.raises(Exception, match='Unauthorized'):
        service.execute_parse_run(session, first.id, source_path=path)
    session.rollback()
    assert len(session.scalars(select(ProcessingStep)).all()) == 1
    service.fail_parse_run(session, first.id, code='failed', message='retry')
    session.commit()
    calls = []
    def second_page(self, messages, **kwargs):
        calls.append(messages)
        return page_result('Page two is now readable.')
    monkeypatch.setattr(DeepSeekClient, 'complete_json', second_page)
    run = service.create_parse_run(session, asset=asset, reparse=True)
    outcome = service.execute_parse_run(session, run.id, source_path=path)
    assert outcome.ir.page_count == 2
    assert len(calls) == 1
    assert outcome.ir.pages[0].text == 'Page one has a real source.'


def test_uncertain_page_never_promotes_partial_read_to_success(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path, pages=1)
    from app.ai.deepseek import DeepSeekClient
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k: {'status': 'unreadable', 'blocks': []})
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(Exception, match='无法读取|不可读'):
        service.execute_parse_run(session, run.id, source_path=path)
    assert service.current_run(session, asset.id) is None


def test_large_pdf_yields_and_resumes_without_loading_all_page_images(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing.llm_reader import ReadingPending
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path, pages=501)
    calls = []
    def answer(self, messages, **kwargs):
        calls.append(messages)
        return page_result()
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(ReadingPending):
        service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
    assert run.page_count == 501
    assert len(calls) == 2
    assert service.current_run(session, asset.id) is None
    assert service.create_parse_run(session, asset=asset).id == run.id
    with pytest.raises(ReadingPending):
        service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
    assert len(calls) == 4
