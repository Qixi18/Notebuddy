import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { CourseKnowledgeStructure } from '../src/pages/CourseKnowledgeStructure'
import { api } from '../src/api'

vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => ({ course: { name: 'Course' } }) }))
vi.mock('../src/api', () => ({ api: { getKnowledgeStructure: vi.fn() } }))
afterEach(cleanup)

test('Notebook filtering keeps identically named sections scoped to their own body', async () => {
  vi.mocked(api.getKnowledgeStructure).mockResolvedValue({ notebooks: [1, 2].map(index => ({
    notebook_id: `book-${index}`, title: `第 ${index} 本`, revision: 3,
    sections: [{ block_id: 'h-1', heading: 'Matrix', excerpt: `第 ${index} 本的正文`, order: 0, level: 1 }],
  })) } as never)
  render(<MemoryRouter initialEntries={['/courses/c']}><Routes>
    <Route path="/courses/:courseId" element={<CourseKnowledgeStructure />} />
  </Routes></MemoryRouter>)
  fireEvent.change(await screen.findByLabelText('筛选笔记本'), { target: { value: 'book-2' } })
  expect(screen.queryByRole('region', { name: '第 1 本' })).toBeNull()
  expect(screen.getByRole('link', { name: /Matrix/ }).getAttribute('href')).toBe('/courses/c/notebooks/book-2?section=h-1')
  expect(screen.getByText('第 2 本的正文')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('搜索知识结构'), { target: { value: '无关内容' } })
  expect(screen.queryByRole('link', { name: /Matrix/ })).toBeNull()
  expect(api.getKnowledgeStructure).toHaveBeenCalledWith('c')
})
