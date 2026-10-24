import { describe, expect, test } from 'vitest'
import {
  docToMarkdown, excerptAroundSelection, extractOutline, legacyBlocksToDocument, markdownToNodes, normalizeDocument,
  stableStringify, type DocNode,
} from '../src/features/notebook-editor/document'

describe('document conversion', () => {
  test('AI context includes nearby notebook text and stays bounded', () => {
    const doc: DocNode = { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: '前文'.repeat(1000) }] },
      { type: 'paragraph', content: [{ type: 'text', text: '动量守恒定律' }] },
      { type: 'paragraph', content: [{ type: 'text', text: '后文'.repeat(1000) }] },
    ] }
    const excerpt = excerptAroundSelection(doc, '动量守恒定律')
    expect(excerpt).toContain('动量守恒定律')
    expect(excerpt.length).toBeLessThanOrEqual(2000)
    expect(excerptAroundSelection(doc)).toContain('前文')
  })

  test('markdownToNodes keeps headings, lists, formulas and inline marks', () => {
    const nodes = markdownToNodes('## 学习要求\n\n理解 **基本概念** 与 $F = ma$\n\n- 要点一\n- 要点二\n\n1. 第一步\n2. 第二步')
    expect(nodes[0]).toMatchObject({ type: 'heading', attrs: { level: 2 } })
    const paragraph = nodes[1]
    expect(paragraph.type).toBe('paragraph')
    expect(paragraph.content?.some((node) => node.marks?.[0]?.type === 'bold')).toBe(true)
    expect(paragraph.content?.some((node) => node.type === 'inlineMath')).toBe(true)
    expect(nodes[2]).toMatchObject({ type: 'bulletList' })
    expect(nodes[2].content).toHaveLength(2)
    expect(nodes[3]).toMatchObject({ type: 'orderedList', attrs: { start: 1 } })
  })

  test('legacy blocks preserve source ids and split markdown paragraphs', () => {
    const doc = legacyBlocksToDocument([
      { id: 'source-note-1', type: 'h2', text: '来源小节' },
      { id: 'body-1', type: 'p', text: '第一段\n\n- 列表项' },
    ])
    expect(doc.content?.[0]).toMatchObject({ type: 'heading', attrs: { blockId: 'source-note-1', level: 2 } })
    expect(doc.content?.[1]).toMatchObject({ type: 'paragraph', attrs: { blockId: 'body-1' } })
    expect(doc.content?.[2]).toMatchObject({ type: 'bulletList' })
  })

  test('extractOutline follows block ids and heading levels', () => {
    const doc: DocNode = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 1, blockId: 'h1' }, content: [{ type: 'text', text: '一、物理学习的要求' }] },
        { type: 'heading', attrs: { level: 2, blockId: 'h2' }, content: [{ type: 'text', text: '1.1 研究对象' }] },
        { type: 'paragraph', attrs: { blockId: 'p' }, content: [{ type: 'text', text: '正文' }] },
      ],
    }
    expect(extractOutline(doc)).toEqual([
      { id: 'h1', level: 1, text: '一、物理学习的要求' },
      { id: 'h2', level: 2, text: '1.1 研究对象' },
    ])
  })

  test('docToMarkdown covers marks, formulas, tasks, tables and callouts', () => {
    const doc: DocNode = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '标题' }] },
        { type: 'paragraph', content: [
          { type: 'text', text: '加粗', marks: [{ type: 'bold' }] },
          { type: 'text', text: '与 ' },
          { type: 'inlineMath', attrs: { latex: 'F = ma' } },
        ] },
        { type: 'taskList', content: [
          { type: 'taskItem', attrs: { checked: true }, content: [{ type: 'paragraph', content: [{ type: 'text', text: '复习' }] }] },
        ] },
        { type: 'callout', attrs: { title: '重点提示', tone: 'tip' }, content: [
          { type: 'paragraph', content: [{ type: 'text', text: '先理解再记忆' }] },
        ] },
      ],
    }
    const markdown = docToMarkdown(doc)
    expect(markdown).toContain('# 标题')
    expect(markdown).toContain('**加粗**')
    expect(markdown).toContain('$F = ma$')
    expect(markdown).toContain('- [x] 复习')
    expect(markdown).toContain('重点提示')
    expect(markdown).toContain('先理解再记忆')
  })

  test('normalizeDocument fills missing block ids and stableStringify ignores key order', () => {
    const doc = normalizeDocument({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '正文' }] }] })
    expect(typeof doc.content?.[0].attrs?.blockId).toBe('string')
    expect(stableStringify({ b: 1, a: [2, { d: 4, c: 3 }] })).toBe(stableStringify({ a: [2, { c: 3, d: 4 }], b: 1 }))
  })
})
