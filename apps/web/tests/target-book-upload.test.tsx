import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { MaterialsPage } from '../src/pages/MaterialsPage'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
vi.mock('../src/api', () => ({ api: { listNotebooks: vi.fn(), getCapabilities: vi.fn().mockResolvedValue(undefined), listDeletedMaterials: vi.fn().mockResolvedValue([]), getForest: vi.fn(), updateForestCourse: vi.fn() } }))
const upload = vi.fn().mockResolvedValue(undefined)
const course = { id: 'c', name: '课程' }
function mount(query = 'notebook=b2') { return render(<MemoryRouter initialEntries={[`/courses/c/materials?${query}`]}><WorkspaceProvider value={{ course, courses: [course], materials: [], pages: [], uploadMaterial: upload } as unknown as WorkspaceContextValue}><MaterialsPage /></WorkspaceProvider></MemoryRouter>) }
beforeEach(() => { vi.clearAllMocks(); upload.mockResolvedValue(undefined); vi.mocked(api.listNotebooks).mockResolvedValue([{ id: 'b1', course_id: 'c', title: '本1' }, { id: 'b2', course_id: 'c', title: '本2' }] as never); vi.mocked(api.getForest).mockResolvedValue({ courses: [{ course_id: 'c', learning_state: 'planned', revision: 7 }] } as never); vi.mocked(api.updateForestCourse).mockResolvedValue({} as never) })
afterEach(cleanup)
test('a root target book remains selected through upload and planned state only changes after the prompt is accepted', async () => {
  const { container } = mount()
  await waitFor(() => expect((screen.getByLabelText('目标笔记本') as HTMLSelectElement).value).toBe('b2'))
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['source'], 'source.docx')] } })
  fireEvent.click(screen.getByRole('button', { name: '上传并解析' }))
  await screen.findByText(/要将森林中的这门课设为“在学”/)
  expect(upload.mock.calls[0][4]).toBe('b2')
  expect(api.updateForestCourse).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '开始学习' }))
  await waitFor(() => expect(api.updateForestCourse).toHaveBeenCalledWith('c', { expected_revision: 7, learning_state: 'learning' }))
})
test('ambiguous and foreign-book targets cannot submit a course-wide upload', async () => {
  const { container } = mount('notebook=foreign')
  await screen.findByText(/目标笔记本不存在或属于其他课程/)
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['source'], 'source.docx')] } })
  expect((screen.getByRole('button', { name: '上传并解析' }) as HTMLButtonElement).disabled).toBe(true)
  expect(upload).not.toHaveBeenCalled()
})
test('failed upload retains the file and target book for a corrected retry', async () => {
  upload.mockRejectedValueOnce(new Error('解析服务不可用'))
  const { container } = mount()
  await waitFor(() => expect((screen.getByLabelText('目标笔记本') as HTMLSelectElement).value).toBe('b2'))
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['source'], 'source.docx')] } })
  fireEvent.click(screen.getByRole('button', { name: '上传并解析' }))
  await waitFor(() => expect(upload.mock.calls.length).toBe(1))
  expect(screen.getByText('source.docx')).toBeTruthy()
  expect((screen.getByLabelText('目标笔记本') as HTMLSelectElement).value).toBe('b2')
  fireEvent.click(screen.getByRole('button', { name: '上传并解析' }))
  await screen.findByText(/要将森林中的这门课设为“在学”/)
})
