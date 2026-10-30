import { Editor } from '@tiptap/core'
import { afterEach, expect, test, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import katex from 'katex'

import { buildExtensions } from '../src/features/notebook-editor/extensions'
import { normalizeDocument } from '../src/features/notebook-editor/document'
import { NotebookEditor } from '../src/features/notebook-editor/NotebookEditor'

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

test('strict KaTeX accepts the supported analysis formula set with trust disabled', () => {
  const formulas = [
    String.raw`\mathbb{R}^n`,
    String.raw`x_k \to a`,
    String.raw`A=\{(x,y)\mid (x-x_0)^2+(y-y_0)^2<\delta^2\}`,
    String.raw`\|x_k-a\|<\varepsilon`,
    String.raw`U(a,\delta)=\{x\in\mathbb{R}^n\mid\|x-a\|<\delta\}`,
    String.raw`A^\circ`,
    String.raw`k\in\mathbb{N}_+`,
    String.raw`\frac{1}{2}mv^2`,
    String.raw`\sqrt{x^2+y^2}`,
    String.raw`\begin{aligned}a&=b+c\\&=d\end{aligned}`,
    String.raw`x \text{ 在中文说明中}`,
  ]

  for (const formula of formulas) {
    expect(() => katex.renderToString(formula, {
      throwOnError: true,
      trust: false,
    })).not.toThrow()
  }
})

test('renders inline math mixed with Chinese prose in paragraphs, callouts, and table cells', async () => {
  let editor: Editor | null = null
  const { container } = render(<NotebookEditor
    initialContent={normalizeDocument({
      type: 'doc',
      content: [
        {
          type: 'paragraph', attrs: { blockId: 'inline-prose' }, content: [
            { type: 'text', text: '设点列 ' },
            { type: 'inlineMath', attrs: { latex: String.raw`x_k \to a` } },
            { type: 'text', text: ' 在 ' },
            { type: 'inlineMath', attrs: { latex: String.raw`\mathbb{R}^n` } },
            { type: 'text', text: ' 中收敛。' },
          ],
        },
        {
          type: 'callout', attrs: { blockId: 'formula-callout', title: '条件', tone: 'note' },
          content: [{ type: 'paragraph', content: [
            { type: 'text', text: '要求 ' },
            { type: 'inlineMath', attrs: { latex: String.raw`\|x-a\|<\varepsilon` } },
          ] }],
        },
        {
          type: 'table', attrs: { blockId: 'formula-table' }, content: [{ type: 'tableRow', content: [
            { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: '表达式' }] }] },
            { type: 'tableCell', content: [{ type: 'paragraph', content: [
              { type: 'inlineMath', attrs: { latex: String.raw`A^\circ` } },
            ] }] },
          ] }],
        },
        { type: 'blockMath', attrs: { blockId: 'block-formula', latex: String.raw`\frac{1}{2}mv^2` } },
      ],
    })}
    onChange={vi.fn()}
    onUploadImage={async () => null}
    onReady={(readyEditor) => { editor = readyEditor }}
  />)

  await waitFor(() => expect(container.querySelectorAll('.katex').length).toBe(5))
  expect(container.querySelectorAll('.katex-error, .inline-math-error, .block-math-error')).toHaveLength(0)
  const json = editor!.getJSON()
  expect((json.content?.[0].attrs as Record<string, unknown>).blockId).toBe('inline-prose')
  expect((json.content?.[1].attrs as Record<string, unknown>).blockId).toBe('formula-callout')
  expect((json.content?.[2].attrs as Record<string, unknown>).blockId).toBe('formula-table')
  expect((json.content?.[3].attrs as Record<string, unknown>).latex).toBe(String.raw`\frac{1}{2}mv^2`)
  expect(json.content?.[0].content?.filter((node) => node.type === 'inlineMath')).toHaveLength(2)
  editor!.destroy()
})

test('keeps unsupported formulas visible as an editable local error instead of hiding them', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: buildExtensions(),
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph', attrs: { blockId: 'bad-inline' }, content: [
          { type: 'text', text: '坏公式：' },
          { type: 'inlineMath', attrs: { latex: String.raw`\notARealCommand{x}` } },
        ],
      }],
    },
    editable: true,
  })

  const math = host.querySelector('[data-type="inline-math"]')
  expect(math?.classList.contains('inline-math-error')).toBe(true)
  expect(math?.textContent).toContain(String.raw`\notARealCommand{x}`)
  expect(editor.isEditable).toBe(true)
  expect(editor.getJSON().content?.[0].content?.[1].attrs?.latex).toBe(String.raw`\notARealCommand{x}`)
  editor.destroy()
})
