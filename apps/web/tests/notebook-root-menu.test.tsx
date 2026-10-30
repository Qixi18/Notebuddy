import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { NotebookRootMenu } from '../src/features/notebook/NotebookRootMenu'

vi.mock('../src/api', () => ({ api: { listNotebooks: vi.fn(), createNotebook: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

test('opening existing notebooks shows a loading state instead of a false empty directory', () => {
  vi.mocked(api.listNotebooks).mockReturnValue(new Promise(() => {}))
  render(<MemoryRouter><NotebookRootMenu courseId="c" courseName="数学" onClose={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '扩充现有笔记本' }))
  expect(screen.getByRole('status').textContent).toContain('正在读取笔记本')
  expect(screen.queryByText('尚无笔记本，请选择新建笔记本。')).toBeNull()
})

test('a failed notebook-directory request can be retried without reopening the dialog', async () => {
  vi.mocked(api.listNotebooks).mockRejectedValueOnce(new Error('目录暂不可用')).mockResolvedValueOnce([])
  render(<MemoryRouter><NotebookRootMenu courseId="c" courseName="数学" onClose={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '扩充现有笔记本' }))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: '重新读取笔记本' }))
  expect(await screen.findByText('尚无笔记本，请选择新建笔记本。')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})
