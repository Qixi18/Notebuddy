import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { ForestRelationsPanel } from '../src/features/forest/ForestRelationsPanel'

vi.mock('../src/api', () => ({
  api: {
    reviewForestRelation: vi.fn(),
    deleteForestRelation: vi.fn(),
    getNotebook: vi.fn(),
    getCourseTree: vi.fn(),
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

test('legacy pending candidates retain explicit review access', async () => {
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
  fireEvent.click(screen.getByRole('button', { name: /待校验/ }))
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
  fireEvent.click(screen.getByRole('button', { name: /待校验/ }))
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
  fireEvent.click(screen.getByRole('button', { name: /待校验/ }))
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

test('automatic active vines show provenance and can be hidden without confirmation', async () => {
  vi.mocked(api.deleteForestRelation).mockResolvedValue({ deleted: true })
  render(<ForestRelationsPanel relations={[{ ...relation, status: 'confirmed', activation_mode: 'automatic' } as never]} courses={[]} onChange={vi.fn()} onClose={vi.fn()} />)
  expect(screen.getByText(/应用关系 · 自动关联/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: '确认关联' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '隐藏关联' }))
  await waitFor(() => expect(api.deleteForestRelation).toHaveBeenCalledWith('r'))
})

test('manual endpoint chooser includes exact real notes in non-default books', async () => {
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [
    { id: id + '-default', title: '默认本', chapters: [], historical_sections: [] },
    { id: id + '-second', title: '第二本', chapters: [{ sections: [{ id: id + '-owned-note', title: '本内同名点' }] }], historical_sections: [] },
  ] }) as never)
  vi.mocked(api.createForestRelation).mockResolvedValue(relation as never)
  render(<ForestRelationsPanel relations={[]} courses={[{ course_id: 'a', name: '数学', note_count: 1 }, { course_id: 'b', name: '机器学习', note_count: 1 }] as never} onChange={vi.fn()} onClose={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '手动连接笔记' }))
  fireEvent.change(screen.getByLabelText('起点课程'), { target: { value: 'a' } })
  fireEvent.change(screen.getByLabelText('终点课程'), { target: { value: 'b' } })
  await screen.findAllByRole('option', { name: '第二本 · 本内同名点' })
  fireEvent.change(screen.getByLabelText('起点笔记'), { target: { value: 'a-owned-note' } })
  fireEvent.change(screen.getByLabelText('终点笔记'), { target: { value: 'b-owned-note' } })
  fireEvent.change(screen.getByLabelText('连接理由'), { target: { value: '两本真实笔记关联' } })
  fireEvent.click(screen.getByRole('button', { name: '建立藤蔓' }))
  await waitFor(() => expect(api.createForestRelation).toHaveBeenCalledWith(expect.objectContaining({ source_note_id: 'a-owned-note', target_note_id: 'b-owned-note' })))
})
