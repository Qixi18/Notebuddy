"""Adapt the shared AI page reader to the curriculum's original-source contract."""
from __future__ import annotations

from app.document_processing import rendering
from app.document_processing.config import route_limits
from app.document_processing.llm_reader import read_page_image, validate_read_page
from app.forest.curriculum_processing import CurriculumProcessingError
from app.parsers.base import ParsedBlock, ParsedDocument, ParsedPage


def read_curriculum_document(run, path):
    pages = []
    with rendering.page_images(path, f'curriculum-{run.record.id}', route_limits('llm')[1]) as (count, render):
        for number in range(1, count + 1):
            try:
                result = run.step('curriculum_read', str(number),
                    [run.snapshot['source_sha256'], number, 'page-vision-v1'],
                    lambda number=number: read_page_image(run.client, render(number), number).model_dump(),
                    lambda value, number=number: validate_read_page(value, number).model_dump())
            except ValueError as exc:
                raise CurriculumProcessingError(f'第 {number} 页读取结果不完整或无法辨认，请检查原页清晰度后重新导入') from exc
            parsed = validate_read_page(result, number)
            blocks = []
            for index, item in enumerate(parsed.blocks):
                text = '\n'.join(' | '.join(row) for row in item.rows) if item.rows else item.text or item.latex or ''
                blocks.append(ParsedBlock(block_type='table' if item.rows else 'text',
                    content=text, position=index, location_label=f'第 {number} 页',
                    extraction_method='vision', warning='模型识别存在不确定内容，请核对原页' if item.uncertain else None))
            pages.append(ParsedPage(page_number=number, title=None,
                raw_text='\n'.join(block.content for block in blocks), blocks=blocks,
                location_label=f'第 {number} 页', extraction_method='vision'))
            run.progress(5 + round(50 * number / count), 'reading')
    return ParsedDocument(format=path.suffix.lstrip('.'), parser_version='curriculum-vision-v1', pages=pages)
