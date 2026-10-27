import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { ForestRelationsPanel } from '../src/features/forest/ForestRelationsPanel'
import type { NotebookRelation } from '../src/features/forest/types'

vi.mock('../src/api', () => ({ api: {
  refreshForestRelation: vi.fn(), deleteForestRelation: vi.fn(), getCourseTree: vi.fn(),
  createForestRelation: vi.fn(), getNotebookBlockSources: vi.fn().mockResolvedValue([]),
} }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const relation: NotebookRelation = {
  id: 'r', source_course_id: 'a', target_course_id: 'b',
  source_notebook_id: 'a-second', target_notebook_id: 'b-second',
  source_block_id: 'h-1', target_block_id: 'h-1',
  source_title: '导数', target_title: '梯度下降',
  source_course_name: '数学', target_course_name: '机器学习',
  relation_type: 'application', reason: '用于优化', created_at: '', origin: 'manual', stale: false,
}
const mount = (props: Partial<Parameters<typeof ForestRelationsPanel>[0]> = {}) => render(
  <MemoryRouter><ForestRelationsPanel courses={[]} relations={[relation]} onChanged={vi.fn()}
    onClose={vi.fn()} {...props} /></MemoryRouter>,
)

test('whole-Notebook links remain visible without fabricating an evidence block', () => {
  mount({ relations: [{ ...relation, source_block_id: null, target_block_id: null }] })
  expect(screen.getByText('用于优化')).toBeTruthy()
  expect(screen.getByRole('link', { name: '数学 · 导数' }).getAttribute('href')).toBe('/courses/a/notebooks/a-second')
  expect(screen.queryByText('核对两端来源')).toBeNull()
})

test('changed body anchors require explicit reconfirmation', async () => {
  const changed = vi.fn()
  vi.mocked(api.refreshForestRelation).mockResolvedValue(relation)
  mount({ relations: [{ ...relation, stale: true }], onChanged: changed })
  expect(screen.getByText(/关联小节的正文已变化/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '确认关联仍有效' }))
  await waitFor(() => expect(api.refreshForestRelation).toHaveBeenCalledExactlyOnceWith('r'))
  expect(changed).toHaveBeenCalledOnce()
})

test('automatic links are labelled as model inference and can be hidden', async () => {
  vi.mocked(api.deleteForestRelation).mockResolvedValue({ deleted: true })
  mount({ relations: [{ ...relation, origin: 'ai' }] })
  expect(screen.getByText('应用关系 · 自动关联（模型推断）')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '隐藏关联' }))
  await waitFor(() => expect(api.deleteForestRelation).toHaveBeenCalledExactlyOnceWith('r'))
})

test('manual chooser links exact body sections in non-default notebooks', async () => {
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [
    { id: id + '-default', course_id: id, title: '默认本', chapters: [], historical_sections: [] },
    { id: id + '-second', course_id: id, title: '第二本', chapters: [{ sections: [{ id: 'h-1', title: '本内同名点' }] }], historical_sections: [] },
  ] }) as never)
  vi.mocked(api.createForestRelation).mockResolvedValue(relation)
  mount({ relations: [], courses: [{ course_id: 'a', name: '数学' }, { course_id: 'b', name: '机器学习' }] as never })
  fireEvent.change(screen.getByLabelText('来源课程'), { target: { value: 'a' } })
  fireEvent.change(screen.getByLabelText('目标课程'), { target: { value: 'b' } })
  await within(screen.getByLabelText('来源笔记')).findByRole('option', { name: '第二本' })
  await within(screen.getByLabelText('目标笔记')).findByRole('option', { name: '第二本' })
  fireEvent.change(screen.getByLabelText('来源笔记'), { target: { value: 'a-second' } })
  fireEvent.change(screen.getByLabelText('目标笔记'), { target: { value: 'b-second' } })
  fireEvent.change(screen.getByLabelText('来源小节'), { target: { value: 'h-1' } })
  fireEvent.change(screen.getByLabelText('目标小节'), { target: { value: 'h-1' } })
  fireEvent.change(screen.getByLabelText('关联依据'), { target: { value: '两本真实笔记关联' } })
  fireEvent.click(screen.getByRole('button', { name: '建立关联' }))
  await waitFor(() => expect(api.createForestRelation).toHaveBeenCalledExactlyOnceWith({
    source_notebook_id: 'a-second', target_notebook_id: 'b-second',
    source_block_id: 'h-1', target_block_id: 'h-1', relation_type: 'related', reason: '两本真实笔记关联',
  }))
})

test('source details refresh when a relation fingerprint changes', async () => {
  let quote = '更新前真实引用'
  vi.mocked(api.getNotebookBlockSources).mockImplementation(async id => id === 'a-second'
    ? [{ asset_name: '资料.pdf', quote, page_number: 1, parse_run_id: 'parse-1', status: 'active' }] : [])
  const props = { relations: [{ ...relation, source_fingerprint: 'before' }], courses: [], onChanged: vi.fn(), onClose: vi.fn() }
  const view = render(<MemoryRouter><ForestRelationsPanel {...props} /></MemoryRouter>)
  const details = screen.getByText('核对两端来源').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  await screen.findByText('更新前真实引用')
  quote = '更新后的真实来源引用'
  view.rerender(<MemoryRouter><ForestRelationsPanel {...props} relations={[{ ...relation, source_fingerprint: 'after' }]} /></MemoryRouter>)
  await screen.findByText('更新后的真实来源引用')
  expect(screen.queryByText('更新前真实引用')).toBeNull()
  expect(api.getNotebookBlockSources).toHaveBeenCalledWith('a-second', 'h-1')
})

test('failed reconfirmation keeps the warning and reports the server reason', async () => {
  const changed = vi.fn()
  vi.mocked(api.refreshForestRelation).mockRejectedValueOnce(new Error('原小节已移除，请重新选择'))
  mount({ relations: [{ ...relation, stale: true }], onChanged: changed })
  fireEvent.click(screen.getByRole('button', { name: '确认关联仍有效' }))
  expect((await screen.findByRole('alert')).textContent).toContain('原小节已移除')
  expect(screen.getByText(/关联小节的正文已变化/)).toBeTruthy()
  expect(changed).not.toHaveBeenCalled()
})
