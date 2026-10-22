import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { HomeSearch } from '../src/features/home/HomeSearch'

vi.mock('../src/api', () => ({ api: { searchForest: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const courses = [{ id: 'outside-home', name: '离散数学', description: null, created_at: '', last_opened_at: null }]
const note = { course_id: 'outside-home', course_name: '离散数学', notebook_id: 'book-2', note_id: 'note-9', title: '图的连通性', material_id: 'lecture-3' }

test('search finds courses beyond the three home trees and opens the exact note identity', async () => {
  vi.mocked(api.searchForest).mockResolvedValue([note])
  const onCourse = vi.fn(), onNote = vi.fn()
  render(<HomeSearch courses={courses} onCourse={onCourse} onNote={onNote} />)
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索课程或知识点' }), { target: { value: '离散' } })
  fireEvent.click(screen.getByRole('button', { name: '课程 离散数学' }))
  expect(onCourse).toHaveBeenCalledWith('outside-home')
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '连通' } })
  fireEvent.click(await screen.findByRole('button', { name: /图的连通性/ }))
  expect(api.searchForest).toHaveBeenLastCalledWith('连通')
  expect(onNote).toHaveBeenCalledWith(note)
})

test('a late response cannot replace newer search results, and Escape dismisses results', async () => {
  let resolveOld!: (value: typeof note[]) => void
  vi.mocked(api.searchForest).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValueOnce([])
  render(<HomeSearch courses={[]} onCourse={vi.fn()} onNote={vi.fn()} />)
  const input = screen.getByRole('searchbox')
  fireEvent.change(input, { target: { value: '旧查询' } })
  await waitFor(() => expect(api.searchForest).toHaveBeenCalledWith('旧查询'))
  fireEvent.change(input, { target: { value: '新查询' } })
  await screen.findByText('没有找到相关课程或知识点')
  resolveOld([note])
  await waitFor(() => expect(screen.queryByRole('button', { name: /图的连通性/ })).toBeNull())
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(screen.queryByRole('region', { name: '搜索结果' })).toBeNull()
})

test('search errors are visible and clearing the query removes the error', async () => {
  vi.mocked(api.searchForest).mockRejectedValue(new Error('暂时无法读取知识点'))
  render(<HomeSearch courses={courses} onCourse={vi.fn()} onNote={vi.fn()} />)
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '连通' } })
  expect((await screen.findByRole('alert')).textContent).toContain('暂时无法读取知识点')
  fireEvent.click(screen.getByRole('button', { name: '清空搜索' }))
  expect(screen.queryByRole('region', { name: '搜索结果' })).toBeNull()
  expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe('')
})
