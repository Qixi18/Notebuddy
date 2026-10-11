import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { ForestRelationsPanel } from '../src/features/forest/ForestRelationsPanel'

vi.mock('../src/api', () => ({
  api: {
    reviewForestRelation: vi.fn(),
    deleteForestRelation: vi.fn(),
    getNotebook: vi.fn(),
    createForestRelation: vi.fn(),
  },
}))
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})
const relation = {
  id: 'r',
  source_course_id: 'a',
  target_course_id: 'b',
  source_note_id: 'na',
  target_note_id: 'nb',
  source_title: '导数',
  target_title: '梯度下降',
  source_course_name: '数学',
  target_course_name: '机器学习',
  relation_type: 'application',
  reason: '用于优化',
  status: 'pending',
  origin: 'ai',
  source_revision: 1,
  target_revision: 1,
  stale: false,
  source_ref_ids: ['sa'],
  target_ref_ids: ['sb'],
}

test('AI candidates require an explicit review before becoming vines', async () => {
  const changed = vi.fn()
  vi.mocked(api.reviewForestRelation).mockResolvedValue({
    ...relation,
    status: 'confirmed',
  } as never)
  render(
    <ForestRelationsPanel
      relations={[relation as never]}
      courses={[]}
      onChange={changed}
      onClose={vi.fn()}
    />,
  )
  expect(screen.getByText('用于优化')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '确认关联' }))
  await waitFor(() => expect(api.reviewForestRelation).toHaveBeenCalledWith('r', 'confirm'))
  expect(changed).toHaveBeenCalled()
})

test('stale candidates cannot be confirmed without regeneration', () => {
  render(
    <ForestRelationsPanel
      relations={[{ ...relation, stale: true } as never]}
      courses={[]}
      onChange={vi.fn()}
      onClose={vi.fn()}
    />,
  )
  expect((screen.getByRole('button', { name: '确认关联' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  expect(screen.getByText(/笔记已修改/)).toBeTruthy()
})

test('explicitly reconnecting a stale relation refreshes the real note anchors', async () => {
  vi.mocked(api.createForestRelation).mockResolvedValue({
    ...relation,
    stale: false,
    status: 'confirmed',
  } as never)
  render(
    <ForestRelationsPanel
      relations={[{ ...relation, stale: true } as never]}
      courses={[]}
      onChange={vi.fn()}
      onClose={vi.fn()}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: '重新核对并连接' }))
  await waitFor(() =>
    expect(api.createForestRelation).toHaveBeenCalledWith({
      source_note_id: 'na',
      target_note_id: 'nb',
      relation_type: 'application',
      reason: '用于优化',
    }),
  )
})
