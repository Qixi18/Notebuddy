"""Synthetic hybrid routing: keep evidence and pay only for doubtful pages."""
from __future__ import annotations

import json

import pytest

from app.document_processing.ir import BlockIR, FigureData, PageIR, TableData

pytest_plugins = ['tests.notebook_fixtures']


def page(text='A derivative measures the rate of change of a function.', **updates):
    result = PageIR(page_id='p1', page_number=1, status='parsed', extraction='native_text',
        text=text, confidence=1.0, blocks=[BlockIR(block_id='b1', page_number=1,
        order=0, global_order=0, type='paragraph', text=text, extraction='native_text')])
    for key, value in updates.items():
        setattr(result, key, value)
    return result


def test_reliable_native_page_avoids_vision():
    from app.document_processing.hybrid import page_needs_vision
    assert page_needs_vision(page()) == []


@pytest.mark.parametrize('candidate', [
    page(status='needs_ocr'), page(status='failed'), page(confidence=0.5),
    page(text='Text containing \ufffd broken glyphs'), page(text='\ue000\ue001 private font glyphs'),
    page(text='函数满足 x^2+y^2=1，求切线。'), page(text='The result is x+y.'),
    page(blocks=[]), page(status='empty', text='', blocks=[]),
    page(blocks=[BlockIR(block_id='e', page_number=1, order=0, global_order=0,
                       type='equation', text='x=2')]),
    page(blocks=[BlockIR(block_id='f', page_number=1, order=0, global_order=0,
                       type='figure', figure=FigureData(uncertain=True))]),
    page(blocks=[BlockIR(block_id='t', page_number=1, order=0, global_order=0,
                       type='table', table=TableData(rows=[]))]),
])
def test_uncertain_local_content_must_not_silently_pass(candidate):
    from app.document_processing.hybrid import page_needs_vision
    assert page_needs_vision(candidate)


def test_structured_equation_and_table_can_remain_local():
    from app.document_processing.hybrid import page_needs_vision
    candidate = page(blocks=[
        BlockIR(block_id='e', page_number=1, order=0, global_order=0,
                type='equation', latex=r'x^2+y^2=1', text=r'x^2+y^2=1', extraction='mineru'),
        BlockIR(block_id='t', page_number=1, order=1, global_order=1,
                type='table', table=TableData(rows=[['x', 'y'], ['1', '2']]), extraction='mineru'),
    ])
    assert page_needs_vision(candidate) == []


def test_provider_snapshot_freezes_hybrid_mode(monkeypatch):
    from app.core.config import settings
    from app.document_processing.config import provider_snapshot
    monkeypatch.setattr(settings, 'llm_reading_mode', 'hybrid')
    assert provider_snapshot()['reading_mode'] == 'hybrid'
    monkeypatch.setattr(settings, 'llm_reading_mode', 'vision')
    assert provider_snapshot()['reading_mode'] == 'vision'


def setup_hybrid(session, tmp_path, monkeypatch, pages=3):
    from app.core.config import settings
    from tests.test_llm_document_processing import setup_pdf
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    asset, path = setup_pdf(session, tmp_path, monkeypatch, pages=pages)
    import fitz
    with fitz.open(path) as pdf:
        for n, pdf_page in enumerate(pdf):
            pdf_page.insert_text((20, 40), f'Visible synthetic evidence on page {n+1}.')
        pdf.saveIncr()
    config = json.loads(asset.processing_config_json)
    config['reading_mode'] = 'hybrid'
    asset.processing_config_json = json.dumps(config)
    session.commit()
    return asset, path


def test_hybrid_reads_only_failed_page_and_preserves_local_sources(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch)
    def local(*args, **kwargs):
        candidates = {}
        for n in (1, 3):
            item = page(f'Complete native evidence on page {n}.')
            item.page_number = n
            candidates[n] = item
        return candidates
    monkeypatch.setattr(hybrid, 'local_pages', local)
    monkeypatch.setattr(hybrid, 'enhance_page', lambda *a, **k: None)
    calls = []
    def answer(self, messages, **kwargs):
        calls.append(messages)
        return {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'Visual page two.'}]}
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    run = service.create_parse_run(session, asset=asset)
    result = service.execute_parse_run(session, run.id, source_path=path)
    assert len(calls) == 1
    assert result.run.parser_name == 'hybrid-local-vision'
    assert [p.extraction for p in result.ir.pages] == ['native_text', 'vision', 'native_text']
    assert [p.text for p in result.ir.pages] == [
        'Complete native evidence on page 1.', 'Visual page two.', 'Complete native evidence on page 3.']
    assert all(b.source.asset_id == asset.id and b.source.page_number == p.page_number
               for p in result.ir.pages for b in p.blocks)
    assert result.ir.quality.generation_allowed


def test_later_failure_reuses_local_and_visual_pages(session, tmp_path, monkeypatch):
    from sqlalchemy import select

    from app.ai.deepseek import DeepSeekClient, DeepSeekError
    from app.db.models import ProcessingStep
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch)
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {1: page()})
    monkeypatch.setattr(hybrid, 'enhance_page', lambda *a, **k: None)
    calls = []
    def answer(self, messages, **kwargs):
        calls.append(messages[-1]['content'][0]['text'])
        if len(calls) == 2:
            raise DeepSeekError('synthetic failure', status_code=401)
        return {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'Recovered evidence.'}]}
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(DeepSeekError):
        service.execute_parse_run(session, run.id, source_path=path)
    session.rollback()
    assert len(session.scalars(select(ProcessingStep)).all()) == 2
    service.fail_parse_run(session, run.id, code='failed', message='retry')
    session.commit()
    retry = service.create_parse_run(session, asset=asset, reparse=True)
    result = service.execute_parse_run(session, retry.id, source_path=path)
    assert len(calls) == 3
    assert '3' in calls[-1]
    assert result.ir.pages[0].blocks[0].block_id.startswith(retry.id[:8])
    assert result.ir.quality.generation_allowed


@pytest.mark.parametrize('bad_result', [
    {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'Maybe', 'uncertain': True}]},
    {'status': 'unreadable', 'blocks': []}, {'status': 'blank', 'blocks': []},
])
def test_visual_fallback_cannot_promote_uncertain_or_false_blank(session, tmp_path, monkeypatch, bad_result):
    from sqlalchemy import select

    from app.ai.deepseek import DeepSeekClient
    from app.db.models import ProcessingStep
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {})
    monkeypatch.setattr(hybrid, 'enhance_page', lambda *a, **k: None)
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k: bad_result)
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(ValueError):
        service.execute_parse_run(session, run.id, source_path=path)
    assert service.current_run(session, asset.id) is None
    assert session.scalar(select(ProcessingStep)) is None


def test_native_text_is_actually_read_without_paid_calls(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing import service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k: pytest.fail('Unexpected paid reading'))
    run = service.create_parse_run(session, asset=asset)
    outcome = service.execute_parse_run(session, run.id, source_path=path)
    assert 'Visible synthetic evidence' in outcome.ir.pages[0].text
    assert outcome.ir.pages[0].extraction == 'native_text'


def test_true_blank_is_confirmed_locally_without_a_model(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing import service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(path)
    monkeypatch.setattr(DeepSeekClient, 'complete_json', lambda *a, **k: pytest.fail('Paid blank-page call'))
    run = service.create_parse_run(session, asset=asset)
    outcome = service.execute_parse_run(session, run.id, source_path=path)
    assert outcome.ir.pages[0].status == 'empty'


def test_bounded_hybrid_yields_and_finishes_without_rereading(session, tmp_path, monkeypatch):
    from app.document_processing import hybrid, service
    from app.document_processing.llm_reader import ReadingPending
    asset, path = setup_hybrid(session, tmp_path, monkeypatch)
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {n: page() for n in (1, 2, 3)})
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(ReadingPending):
        service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
    result = service.execute_parse_run(session, run.id, source_path=path, max_new_pages=2)
    assert len(result.ir.pages) == 3
    assert [p.page_number for p in result.ir.pages] == [1, 2, 3]


def test_local_reader_extracts_only_requested_original_page(session, tmp_path, monkeypatch):
    from app.document_processing.adapters.pdf import ParseContext
    from app.document_processing.hybrid import local_pages
    asset, path = setup_hybrid(session, tmp_path, monkeypatch)
    pages = local_pages(path, ParseContext(asset_id=asset.id, parse_run_id='synthetic'), page_numbers=[2])
    assert list(pages) == [2]
    assert 'page 2' in pages[2].text


def test_model_snapshot_change_invalidates_successful_page_cache(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {})
    monkeypatch.setattr(hybrid, 'enhance_page', lambda *a, **k: None)
    calls = []
    def answer(*args, **kwargs):
        calls.append(1)
        return {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'Valid evidence.'}]}
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    first = service.create_parse_run(session, asset=asset)
    service.execute_parse_run(session, first.id, source_path=path)
    session.commit()
    config = json.loads(asset.processing_config_json)
    config['model'] = 'changed-text-model'
    asset.processing_config_json = json.dumps(config)
    session.commit()
    second = service.create_parse_run(session, asset=asset, reparse=True)
    service.execute_parse_run(session, second.id, source_path=path)
    assert len(calls) == 2


def test_cancel_during_visual_request_discards_result(session, tmp_path, monkeypatch):
    from sqlalchemy import select

    from app.ai.deepseek import DeepSeekClient
    from app.db.models import ProcessingStep
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {})
    monkeypatch.setattr(hybrid, 'enhance_page', lambda *a, **k: None)
    run = service.create_parse_run(session, asset=asset)
    cancelled = False
    def answer(*args, **kwargs):
        nonlocal cancelled
        cancelled = True
        return {'status': 'read', 'blocks': [{'type': 'paragraph', 'text': 'Too late.'}]}
    def progress(done, total):
        if cancelled:
            raise RuntimeError('资料处理已停止')
    monkeypatch.setattr(DeepSeekClient, 'complete_json', answer)
    with pytest.raises(RuntimeError, match='已停止'):
        service.execute_parse_run(session, run.id, source_path=path, progress=progress)
    assert service.current_run(session, asset.id) is None
    assert session.scalar(select(ProcessingStep)) is None


def test_native_and_mineru_failure_still_uses_budgeted_visual_fallback(session, tmp_path, monkeypatch):
    from app.ai.deepseek import DeepSeekClient, DeepSeekError
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    def broken(*args, **kwargs):
        raise RuntimeError('Synthetic local failure')
    monkeypatch.setattr(hybrid, 'local_pages', broken)
    monkeypatch.setattr(hybrid, 'enhance_page', broken)
    calls = []
    def blocked(*args, **kwargs):
        calls.append(1)
        raise DeepSeekError('Budget gate blocked request', code='budget_exceeded')
    monkeypatch.setattr(DeepSeekClient, 'complete_json', blocked)
    run = service.create_parse_run(session, asset=asset)
    with pytest.raises(service.DocumentProcessingError) as caught:
        service.execute_parse_run(session, run.id, source_path=path)
    assert caught.value.code == 'budget_exceeded'
    assert len(calls) == 1


def test_local_mineru_mapping_never_invokes_remote_enrichment(monkeypatch):
    from app.document_processing.adapters import mineru
    calls = []
    monkeypatch.setattr(mineru, '_enrich_mineru_figure', lambda *a, **k: calls.append(1) or [])
    blocks = mineru._map_item({'type': 'image', 'content': {}}, block_id='b1',
        page_number=1, order=0, global_order=0, asset_id='synthetic',
        image_fallback=lambda box: 'derived/synthetic.png', allow_vision=False)
    assert not calls
    assert blocks[0].figure.uncertain


@pytest.mark.parametrize('script_baseline', [65, 75])
def test_small_raised_glyph_in_prose_cannot_pass_as_plain_native_text(session, tmp_path, monkeypatch, script_baseline):
    import fitz

    from app.document_processing.adapters.pdf import ParseContext
    from app.document_processing.hybrid import local_pages, page_needs_vision
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    document = fitz.open()
    p = document.new_page()
    p.insert_text((30, 70), 'The quantity x', fontsize=12)
    x = 30 + fitz.get_text_length('The quantity x', fontsize=12)
    p.insert_text((x, script_baseline), '2', fontsize=8)
    p.insert_text((x + 5, 70), ' describes the curve.', fontsize=12)
    document.save(path)
    document.close()
    candidate = local_pages(path, ParseContext(asset_id=asset.id, parse_run_id='scripted'))[1]
    assert '2' in candidate.text
    assert page_needs_vision(candidate), 'Superscript geometry must trigger structure recovery'


def test_small_formula_image_is_not_dropped_as_decoration(session, tmp_path, monkeypatch):
    from io import BytesIO

    import fitz
    from PIL import Image, ImageDraw

    from app.document_processing.adapters.pdf import ParseContext
    from app.document_processing.hybrid import local_pages, page_needs_vision
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    image = Image.new('RGB', (40, 30), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((15, 0), 'x', fill='black')
    draw.line((10, 14, 30, 14), fill='black')
    draw.text((15, 16), 'y', fill='black')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    document = fitz.open()
    p = document.new_page()
    p.insert_text((30, 60), 'The ratio is shown below.')
    p.insert_image(fitz.Rect(100, 80, 140, 110), stream=buffer.getvalue())
    document.save(path)
    document.close()
    candidate = local_pages(path, ParseContext(asset_id=asset.id, parse_run_id='small-image'))[1]
    assert page_needs_vision(candidate), 'A tiny formula cannot silently disappear'


def test_vector_fraction_cannot_pass_as_three_plain_text_lines(session, tmp_path, monkeypatch):
    import fitz

    from app.document_processing.adapters.pdf import ParseContext
    from app.document_processing.hybrid import local_pages, page_needs_vision
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    document = fitz.open()
    p = document.new_page()
    p.insert_text((30, 60), 'A ratio describes these quantities.')
    p.insert_text((112, 85), 'x', fontname='tiro', fontsize=12)
    p.insert_text((112, 105), 'y', fontname='tiro', fontsize=12)
    p.draw_line((105, 90), (125, 90))
    document.save(path)
    document.close()
    candidate = local_pages(path, ParseContext(asset_id=asset.id, parse_run_id='fraction'))[1]
    assert page_needs_vision(candidate), 'Vector fraction bar must not disappear from evidence'


def test_text_only_engine_without_layout_evidence_cannot_be_trusted(session, tmp_path, monkeypatch):
    from app.document_processing.adapters.pdf import ParseContext
    from app.document_processing.engines import pdf_text
    from app.document_processing.hybrid import local_pages, page_needs_vision
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    monkeypatch.setattr(pdf_text, '_pymupdf', lambda: None)
    candidate = local_pages(path, ParseContext(asset_id=asset.id, parse_run_id='fallback'))[1]
    assert 'layout_evidence_uncertain' in page_needs_vision(candidate)


def test_local_mineru_refuses_package_external_llm_helpers(monkeypatch):
    from pathlib import Path
    package_config = pytest.importorskip('mineru.config')
    from app.document_processing.adapters import mineru
    from app.document_processing.adapters.pdf import ParseContext
    monkeypatch.setattr(package_config.config.llm_aided.features, 'title_leveling', True)
    with pytest.raises(mineru.MinerUUnavailable, match='禁用外部模型'):
        mineru.parse_document(Path('synthetic.pdf'), ParseContext(asset_id='a', parse_run_id='r'),
                              tier='basic', local_only=True)


def test_long_local_evidence_is_split_losslessly_before_ai_planning(session, tmp_path, monkeypatch):
    from app.document_processing import hybrid, service
    asset, path = setup_hybrid(session, tmp_path, monkeypatch, pages=1)
    original = 'Reliable evidence must survive every split. ' * 1000
    monkeypatch.setattr(hybrid, 'local_pages', lambda *a, **k: {1: page(original)})
    run = service.create_parse_run(session, asset=asset)
    result = service.execute_parse_run(session, run.id, source_path=path)
    blocks = result.ir.pages[0].blocks
    assert len(blocks) > 1
    assert all(len(b.text) <= 2000 for b in blocks)
    assert ''.join(b.text for b in blocks) == original
    assert result.ir.sections[0].block_ids == [b.block_id for b in blocks]
