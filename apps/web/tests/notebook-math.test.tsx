import { Editor } from '@tiptap/core'
import { afterEach, expect, test } from 'vitest'

import { buildExtensions } from '../src/features/notebook-editor/extensions'
import { normalizeDocument } from '../src/features/notebook-editor/document'

const latex = String.raw`A \cup B = \{x \mid x \in A \text{或} x \in B\}. \tag{1.1}`

afterEach(() => {
  document.body.innerHTML = ''
})

test('converts a standalone raw-LaTeX paragraph to a block math node and keeps its source ID', () => {
  const normalized = normalizeDocument({
    type: 'doc',
    content: [{
      type: 'paragraph',
      attrs: { blockId: 'source-block-1' },
      content: [{ type: 'text', text: latex }],
    }],
  })

  expect(normalized.content).toEqual([{
    type: 'blockMath',
    attrs: { latex, blockId: 'source-block-1' },
  }])
})

test('keeps explanatory prose containing an inline LaTeX command as a paragraph', () => {
  const normalized = normalizeDocument({
    type: 'doc',
    content: [{
      type: 'paragraph',
      attrs: { blockId: 'prose-1' },
      content: [{ type: 'text', text: String.raw`其中 x \in A 表示 x 属于集合 A。` }],
    }],
  })

  expect(normalized.content?.[0].type).toBe('paragraph')
})

test('renders block formulas in KaTeX display mode and preserves block IDs in editor JSON', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: buildExtensions(),
    content: normalizeDocument({
      type: 'doc',
      content: [{ type: 'blockMath', attrs: { latex, blockId: 'math-block-1' } }],
    }),
    editable: false,
  })

  expect(host.querySelector('[data-type="block-math"] .katex-display')).toBeTruthy()
  expect(host.querySelector('[data-type="block-math"] .katex-error')).toBeFalsy()
  expect(host.querySelector('[data-type="block-math"]')?.textContent).toContain('∪')
  expect(host.querySelector('[data-type="block-math"]')?.textContent).toContain('或')
  expect((editor.getJSON().content?.[0].attrs as Record<string, unknown>).blockId).toBe('math-block-1')
  editor.destroy()
})
