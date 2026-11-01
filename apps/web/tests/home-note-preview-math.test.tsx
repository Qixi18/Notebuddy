import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HomeNotePreview } from '../src/features/home/HomeNotePreview'
import type { HomeLeafPreview } from '../src/features/home/HomeCourseTree'
import { api } from '../src/api'

vi.mock('../src/api', () => ({ api: { getNotebookSections: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

function preview(text: string, title = '集合的概念与表示') {
  vi.mocked(api.getNotebookSections).mockResolvedValue([{ block_id: 'section', excerpt: text }] as never)
  const item = {
    book: { id: 'book', course_id: 'course', title: '数学' },
    leaf: { section: { id: 'section', block_id: 'section', notebook_id: 'book', title, revision_number: 1 }, chapterTitle: '第1节' },
    target: document.createElementNS('http://www.w3.org/2000/svg', 'ellipse'),
  } as HomeLeafPreview
  return render(<HomeNotePreview id="preview" preview={item} courseId="course" onEnter={vi.fn()} onLeave={vi.fn()} onDismiss={vi.fn()} />)
}

test('leaf previews typeset set notation and blackboard-bold letters alongside Chinese prose', async () => {
  preview(String.raw`定义：集合由确定的对象组成。$a\in A$ 表示属于，$a\notin A$ 表示不属于。自然数集 $\mathbb{N}$，整数集 $\mathbb{Z}$。`)
  const tooltip = screen.getByRole('tooltip')
  await waitFor(() => expect(tooltip.querySelectorAll('.katex')).toHaveLength(4))
  expect(tooltip.querySelector('.katex-error')).toBeNull()
  expect(tooltip.querySelector('.katex-html')?.textContent).toContain('∈')
  expect(tooltip.textContent).toContain('定义：集合由确定的对象组成。')
  expect(tooltip.querySelectorAll('.katex-mathml annotation')).toHaveLength(4)
})

test('a preview does not cut a complete formula at the former 145-character boundary', async () => {
  const latex = String.raw`\frac{a_1+a_2+\cdots+a_n}{n}\in\mathbb{R}`
  preview(`${'这里是公式前的说明。'.repeat(14)} $${latex}$ 后续解释。`)
  const tooltip = screen.getByRole('tooltip')
  await waitFor(() => expect(tooltip.querySelector('.katex')).not.toBeNull())
  expect(tooltip.querySelector('annotation')?.textContent).toBe(latex)
  expect(tooltip.querySelector('.katex-error')).toBeNull()
})

test('leaf preview headings support inline formulas too', async () => {
  preview('正文说明。', String.raw`函数 $f(x)=x^2$ 的性质`)
  const heading = screen.getByRole('tooltip').querySelector('strong')!
  await waitFor(() => expect(heading.querySelector('.katex')).not.toBeNull())
  expect(heading.querySelector('annotation')?.textContent).toBe('f(x)=x^2')
})

test('preview markdown remains read-only and does not load remote images or raw HTML', async () => {
  preview('正文 [参考](https://example.test) ![远程图片](https://example.test/image.png) <img src="https://example.test/raw.png">')
  const tooltip = screen.getByRole('tooltip')
  await waitFor(() => expect(tooltip.textContent).toContain('参考'))
  expect(tooltip.querySelector('img')).toBeNull()
  expect(tooltip.querySelector('a')).toBeNull()
})
