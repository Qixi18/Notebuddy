import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'
import { NotebookPage } from '../src/pages/NotebookPage'
vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getCourseTree: vi.fn(), getNotebookById: vi.fn(), getReadingPosition: vi.fn().mockResolvedValue(null), getNotebookChapter: vi.fn().mockResolvedValue({ sections: [] }), saveReadingPosition: vi.fn().mockResolvedValue({ revision: 1 }) } }))
vi.mock('../src/features/notes/NoteSectionReader', () => ({ NoteSectionReader: ({ noteId }: { noteId: string }) => <p>正文 {noteId}</p> }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear() })
test('home leaf to another chapter retains return to the original home collection and camera', async () => {
  const section = { id: 'n1', notebook_id: 'book', material_id: 'm1', tree_slot: 0, title: '知识点' }
  const next = { ...section, id: 'n2', material_id: 'm2', tree_slot: 1, title: '下一讲知识点' }
  const book = { id: 'book', course_id: 'c0', title: '课程本', tree_slot: 0, order_revision: 0, chapters: [{ id: 'm1', title: '第一讲', sections: [section] }, { id: 'm2', title: '第二讲', sections: [next] }], historical_sections: [], removed_chapters: [] }
  const courses = Array.from({ length: 4 }, (_, i) => ({ id: `c${i}`, name: `课${i}`, created_at: `2026-10-0${5 - i}`, last_opened_at: null }))
  vi.mocked(api.getForest).mockResolvedValue({ courses: courses.map(course => ({ course_id: course.id, name: course.name, semester: 1, position: 0, level: 'foundation', learning_state: 'learning', revision: 0, prerequisites: [] })) } as never)
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: id === 'c0' ? [book] : [] }) as never)
  vi.mocked(api.getNotebookById).mockResolvedValue(book as never)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1700, height: 720 } as DOMRect)
  function Fixture() {
    const [items, setItems] = useState(courses)
    return <WorkspaceProvider value={{ courses: items, coursesLoading: false, notes: [section, next], materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn() } as unknown as WorkspaceContextValue}><button onClick={() => setItems(current => current.map(course => course.id === 'c3' ? { ...course, last_opened_at: '2027-01-01' } as never : course))}>访问第四课</button><Routes><Route path="/" element={<HomePage />} /><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></WorkspaceProvider>
  }
  const { container } = render(<MemoryRouter><Fixture /></MemoryRouter>)
  await screen.findByRole('button', { name: '打开知识点：知识点' })
  fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识点' }))
  const saved = JSON.parse(sessionStorage.getItem('notebuddy.scene.home:default')!).view.camera
  await screen.findByText('正文 n1')
  fireEvent.click(screen.getByRole('button', { name: '访问第四课' }))
  fireEvent.click(screen.getByRole('button', { name: '2. 第二讲' }))
  await screen.findByText('正文 n2')
  fireEvent.click(screen.getByRole('link', { name: /返回课程树/ }))
  await screen.findByRole('button', { name: '打开知识点：知识点' })
  await waitFor(() => expect(container.querySelector('.kt-canvas > g')!.getAttribute('transform')).toBe(`translate(${saved.x},${saved.y}) scale(${saved.k})`))
  expect(container.querySelector('[data-course-id="c3"]')).toBeNull()
  expect(container.querySelector('[data-course-id="c2"]')).toBeTruthy()
})
