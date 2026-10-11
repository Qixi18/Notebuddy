import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { CurriculumImportPanel } from '../src/features/forest/CurriculumImportPanel'
vi.mock('../src/api', () => ({
  api: {
    listCurriculumImports: vi.fn(),
    createCurriculumImport: vi.fn(),
    confirmCurriculumImport: vi.fn(),
    getCurriculumImport: vi.fn(),
  },
}))
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})
test('curriculum preview permits corrections and creates courses only after confirmation', async () => {
  const row = {
    key: 'row1',
    name: 'Calculus',
    semester: 1,
    level: 'foundation',
    prerequisites: [],
    source_label: '段落 1',
    source_excerpt: 'Calculus 第一学期',
    existing_course_id: null,
  }
  vi.mocked(api.listCurriculumImports).mockResolvedValue([])
  vi.mocked(api.createCurriculumImport).mockResolvedValue({
    id: 'i',
    status: 'preview',
    filename: null,
    mode: 'local_rules',
    warnings: ['本地规则提取'],
    rows: [row],
    error_message: null,
    job_id: 'j',
  } as never)
  vi.mocked(api.confirmCurriculumImport).mockResolvedValue({ courses: [] })
  render(<CurriculumImportPanel courses={[]} onConfirmed={vi.fn()} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('粘贴培养方案'), {
    target: { value: 'Calculus 第一学期' },
  })
  fireEvent.click(screen.getByRole('button', { name: '解析并预览' }))
  await screen.findByDisplayValue('Calculus')
  expect(api.confirmCurriculumImport).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('课程名称 1'), { target: { value: '高等数学' } })
  fireEvent.click(screen.getByRole('button', { name: '确认课程方案' }))
  await waitFor(() =>
    expect(api.confirmCurriculumImport).toHaveBeenCalledWith('i', [{ ...row, name: '高等数学' }]),
  )
})

test('excluding a duplicate preview row confirms only selected original evidence', async () => {
  const row = {
    key: 'row1',
    name: '高等数学',
    semester: 1,
    level: 'foundation',
    prerequisites: [],
    source_label: '段落 1',
    source_excerpt: '原文课程表',
    existing_course_id: null,
  }
  vi.mocked(api.listCurriculumImports).mockResolvedValue([])
  vi.mocked(api.createCurriculumImport).mockResolvedValue({
    id: 'i',
    status: 'preview',
    filename: null,
    mode: 'local_rules',
    warnings: [],
    rows: [row, { ...row, key: 'row2', source_label: '段落 2', source_excerpt: '原文分学期表' }],
    error_message: null,
    job_id: 'j',
  } as never)
  vi.mocked(api.confirmCurriculumImport).mockResolvedValue({ courses: [] })
  render(<CurriculumImportPanel courses={[]} onConfirmed={vi.fn()} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('粘贴培养方案'), {
    target: { value: '培养方案课程表与分学期课程表' },
  })
  fireEvent.click(screen.getByRole('button', { name: '解析并预览' }))
  fireEvent.click(await screen.findByRole('button', { name: '不导入课程 2' }))
  fireEvent.click(screen.getByRole('button', { name: '确认课程方案' }))
  await waitFor(() => expect(api.confirmCurriculumImport).toHaveBeenCalledWith('i', [row]))
})
