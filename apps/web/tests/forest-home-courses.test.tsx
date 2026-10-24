import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../src/api'
import { ForestPage } from '../src/pages/ForestPage'
import type { ForestCourse } from '../src/features/forest/types'

vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => ({ refreshCourses: vi.fn() }) }))
vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn().mockResolvedValue([]), getCourseTree: vi.fn(async (id: string) => ({ course_id: id, notebooks: [] })), getLatestForestJob: vi.fn().mockResolvedValue(null), updateForestCourse: vi.fn() } }))
let rows: ForestCourse[]
beforeEach(() => {
  rows = Array.from({ length: 4 }, (_, i) => ({ course_id: `c${i}`, name: `课程${i}`, position: i, revision: 7, learning_state: i < 3 ? 'learning' : 'planned', semester: null, level: 'unspecified', prerequisites: [], note_count: 0, material_count: 0 }))
  vi.mocked(api.getForest).mockImplementation(async () => ({ courses: structuredClone(rows) }))
  vi.mocked(api.updateForestCourse).mockImplementation(async (id, change) => {
    const next = { ...rows.find(row => row.course_id === id)!, ...change, revision: change.expected_revision + 1 }
    rows = rows.map(row => row.course_id === id ? next : row)
    return next
  })
})
afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear() })

it('prevents a fourth home course and allows choosing it after removing one', async () => {
  render(<MemoryRouter><ForestPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: /首页正在学/ }))
  const manager = within(screen.getByRole('dialog', { name: '选择首页课程' }))
  const fourth = manager.getByRole('button', { name: '放到首页：课程3' }) as HTMLButtonElement
  expect(fourth.disabled).toBe(true)
  fireEvent.click(fourth)
  expect(api.updateForestCourse).not.toHaveBeenCalled()
  fireEvent.click(manager.getByRole('button', { name: '移出首页：课程0' }))
  await waitFor(() => expect((manager.getByRole('button', { name: '放到首页：课程3' }) as HTMLButtonElement).disabled).toBe(false))
  expect(api.updateForestCourse).toHaveBeenLastCalledWith('c0', { expected_revision: 7, learning_state: 'planned' })
  fireEvent.click(manager.getByRole('button', { name: '放到首页：课程3' }))
  await manager.findByRole('button', { name: '移出首页：课程3' })
  expect(api.updateForestCourse).toHaveBeenLastCalledWith('c3', { expected_revision: 7, learning_state: 'learning' })
})

it('keeps membership unchanged when saving fails and reports the error', async () => {
  vi.mocked(api.updateForestCourse).mockRejectedValueOnce(new Error('课程状态保存失败'))
  render(<MemoryRouter><ForestPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: /首页正在学/ }))
  const manager = within(screen.getByRole('dialog', { name: '选择首页课程' }))
  fireEvent.click(manager.getByRole('button', { name: '移出首页：课程0' }))
  expect((await manager.findByRole('alert')).textContent).toContain('课程状态保存失败')
  expect(manager.getByRole('button', { name: '移出首页：课程0' })).toBeTruthy()
})

it('supports the tree-root home shortcut without opening the notebook menu', async () => {
  render(<MemoryRouter initialEntries={['/forest?course=c0']}><ForestPage /></MemoryRouter>)
  fireEvent.keyDown(await screen.findByRole('button', { name: '移出首页：课程0' }), { key: 'Enter' })
  await waitFor(() => expect(api.updateForestCourse).toHaveBeenCalledWith('c0', { expected_revision: 7, learning_state: 'planned' }))
  await screen.findByRole('button', { name: '放到首页：课程0' })
  expect(screen.queryByRole('dialog', { name: '课程0笔记本操作' })).toBeNull()
})
