import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { CurriculumImportPanel } from '../src/features/forest/CurriculumImportPanel'
import type { CurriculumImport } from '../src/features/forest/types'
vi.mock('../src/api', () => ({
  api: {
    listCurriculumImports: vi.fn(),
    createCurriculumImport: vi.fn(),
    confirmCurriculumImport: vi.fn(),
    getCurriculumImport: vi.fn(),
    retryCurriculumImport: vi.fn(),
    previewCurriculumRevert: vi.fn(),
    revertCurriculumImport: vi.fn(),
  },
}))
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

test('retry resumes progress polling and eventually shows the editable preview', async () => {
  const row = { key: 'source-1', name: '高等数学', semester: 1, level: 'foundation',
    prerequisites: [], source_label: '第 1 页', source_excerpt: '高等数学 | 1', existing_course_id: null }
  const failed = { id: 'retry-import', status: 'failed', filename: null, mode: 'ai', warnings: [],
    rows: [], error_message: '临时失败', job_id: 'job', progress: 45 } as CurriculumImport
  vi.mocked(api.listCurriculumImports).mockResolvedValue([failed])
  vi.mocked(api.retryCurriculumImport).mockResolvedValue({ ...failed, status: 'pending', error_message: null } as never)
  vi.mocked(api.getCurriculumImport).mockResolvedValue({ ...failed, status: 'preview', rows: [row], error_message: null, progress: 100 } as never)
  render(<CurriculumImportPanel courses={[]} onConfirmed={vi.fn()} onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /粘贴文本.*失败/ }))
  fireEvent.click(screen.getByRole('button', { name: '重试解析' }))
  await screen.findByRole('status')
  expect((screen.getByRole('progressbar') as HTMLProgressElement).value).toBe(45)
  expect(await screen.findByDisplayValue('高等数学', {}, { timeout: 3000 })).toBeTruthy()
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

test('excluded edits can be restored before confirming', async () => {
  const row = { key: 'r', name: '数学', semester: 1, level: 'foundation', prerequisites: [], source_label: '行 1', source_excerpt: '数学 | 1', existing_course_id: null }
  vi.mocked(api.listCurriculumImports).mockResolvedValue([{ id: 'i', status: 'preview', filename: '方案.pdf', mode: 'ai', warnings: [], rows: [row], error_message: null, job_id: 'j' } as never])
  render(<CurriculumImportPanel courses={[]} onConfirmed={vi.fn()} onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /方案.pdf/ }))
  fireEvent.change(screen.getByLabelText('课程名称 1'), { target: { value: '数学 I' } })
  fireEvent.click(screen.getByRole('button', { name: '不导入课程 1' }))
  expect(screen.queryByLabelText('课程名称 1')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '恢复 数学 I' }))
  expect(screen.getByDisplayValue('数学 I')).toBeTruthy()
})

test('revert displays concrete impact and requires a second explicit action', async () => {
  const confirmed: CurriculumImport = { id: 'i', status: 'confirmed', filename: '方案.pdf', mode: 'ai', warnings: [], rows: [], error_message: null, job_id: 'j', can_revert: true }
  vi.mocked(api.listCurriculumImports).mockResolvedValue([confirmed])
  vi.mocked(api.previewCurriculumRevert).mockResolvedValue({ restore_courses: [], recycle_courses: [{ course_id: 'new', name: '数学' }] })
  vi.mocked(api.revertCurriculumImport).mockResolvedValue({ ...confirmed, status: 'reverted', can_revert: false })
  const refresh = vi.fn()
  render(<CurriculumImportPanel courses={[]} onConfirmed={refresh} onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /方案.pdf/ }))
  fireEvent.click(screen.getByRole('button', { name: '查看撤销影响' }))
  await screen.findByText('移入回收站：数学（新建且未使用）')
  expect(api.revertCurriculumImport).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '确认撤销这次导入' }))
  await waitFor(() => expect(api.revertCurriculumImport).toHaveBeenCalledWith('i'))
  expect(refresh).toHaveBeenCalledOnce()
})
