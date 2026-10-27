import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const apiState = vi.hoisted(() => ({ listNotebooks: vi.fn() }))
vi.mock('../src/api', () => ({ api: { listNotebooks: apiState.listNotebooks } }))

import { LegacyMaterialsRedirect } from '../src/App'

function Destination() {
  const location = useLocation()
  return <p>{location.pathname}{location.search}</p>
}

function mount(path: string) {
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/courses/:courseId/materials" element={<LegacyMaterialsRedirect />} />
    <Route path="/courses/:courseId/notebooks/:notebookId" element={<Destination />} />
    <Route path="/courses/:courseId" element={<Destination />} />
  </Routes></MemoryRouter>)
}

beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)

test('old materials links open the explicitly selected Notebook', async () => {
  apiState.listNotebooks.mockResolvedValue([
    { id: 'book-a', course_id: 'c', title: '第一本' },
    { id: 'book-b', course_id: 'c', title: '第二本' },
  ])
  mount('/courses/c/materials?notebook=book-b')
  expect(await screen.findByText('/courses/c/notebooks/book-b')).toBeTruthy()
  expect(apiState.listNotebooks).toHaveBeenCalledWith('c')
})

test('invalid Notebook links return to the course overview instead of switching books', async () => {
  apiState.listNotebooks.mockResolvedValue([{ id: 'book-a', course_id: 'c', title: '第一本' }])
  mount('/courses/c/materials?notebook=missing')
  expect(await screen.findByText('/courses/c')).toBeTruthy()
})

test('courses without Notebooks return to the course overview', async () => {
  apiState.listNotebooks.mockResolvedValue([])
  mount('/courses/c/materials')
  expect(await screen.findByText('/courses/c')).toBeTruthy()
})
