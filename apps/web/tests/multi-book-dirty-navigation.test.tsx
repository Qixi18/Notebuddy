import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, useNavigate, useLocation } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { AppLayout, WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
afterEach(() => { cleanup(); localStorage.clear() })
function Page() { const navigate = useNavigate(), location = useLocation(); return <><p>{location.pathname}{location.search}</p><button onClick={() => navigate('/courses/c/notebooks/second?section=n2')}>打开另一本叶子</button></> }
test('multi-book leaf navigation keeps an unsaved draft until the user chooses to leave', async () => {
  localStorage.setItem('notebuddy.assistant.open', 'false')
  const workspace = { courses: [], noteDirty: true, setEditingNote: vi.fn(), setError: vi.fn() } as unknown as WorkspaceContextValue
  const router = createMemoryRouter([{ element: <AppLayout />, children: [{ path: '/courses/:courseId/notebooks/:notebookId', element: <Page /> }] }], { initialEntries: ['/courses/c/notebooks/first?section=n1'] })
  render(<WorkspaceProvider value={workspace}><RouterProvider router={router} /></WorkspaceProvider>)
  fireEvent.click(screen.getByRole('button', { name: '打开另一本叶子' }))
  expect(await screen.findByRole('dialog', { name: '离开正在编辑的笔记？' })).toBeTruthy()
  expect(screen.getByText('/courses/c/notebooks/first?section=n1')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '继续编辑' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '打开另一本叶子' }))
  fireEvent.click(screen.getByRole('button', { name: '放弃草稿并离开' }))
  expect(await screen.findByText('/courses/c/notebooks/second?section=n2')).toBeTruthy()
})
