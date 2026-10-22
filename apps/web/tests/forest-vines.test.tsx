import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { TreeVines } from '../src/features/tree/TreeVines'
import { buildVine, resolveVineLod, vinePoint } from '../src/features/tree/vineGeometry'
import type { CrossCourseRelation } from '../src/features/forest/types'

afterEach(cleanup)
it('routes a triangle edge through the reserved gap below the upper tree', () => {
  const midpoint = { x: 500, y: 400 }
  const vine = buildVine({ id: 'triangle', order: 0, start: { x: 200, y: 250 }, end: { x: 800, y: 250 }, relationIds: ['r'], midpoint })
  expect(vinePoint(vine.curves, .5)).toEqual(midpoint)
  // A hanging edge descends smoothly into its low point instead of making an
  // upward hook at either graft before bending around the middle tree.
  for (let step = 1; step <= 10; step++) {
    expect(vinePoint(vine.curves, step / 20).y).toBeGreaterThan(vinePoint(vine.curves, (step - 1) / 20).y)
    expect(vinePoint(vine.curves, 1 - step / 20).y).toBeGreaterThan(vinePoint(vine.curves, 1 - (step - 1) / 20).y)
  }
})
it('keeps relationship leaf targets clear of course captions even when selected', () => {
  const vine = buildVine({ id: 'caption', order: 0, start: { x: 0, y: 0 }, end: { x: 600, y: 0 }, relationIds: ['real-relation'] })
  const { center } = vine.leaves[0]
  expect(resolveVineLod([vine], 1, 'real-relation').visible).toContain('real-relation')
  const result = resolveVineLod([vine], 1, 'real-relation', [{ rect: { x: center.x - 30, y: center.y - 30, width: 60, height: 60 } }])
  expect(result.visible).not.toContain('real-relation')
  expect(result.hidden).toContain('real-relation')
})
const relation = (index: number, extra = {}): CrossCourseRelation => ({
  id: `r-${index}`, source_course_id: 'a', target_course_id: 'b', source_note_id: `a-${index}`, target_note_id: `b-${index}`,
  source_title: `源${index}`, target_title: `目标${index}`, source_course_name: '课程甲', target_course_name: '课程乙',
  relation_type: 'related', reason: `依据${index}`, status: 'confirmed', origin: 'ai', activation_mode: 'automatic', evidence_fingerprint: null,
  source_revision: 1, target_revision: 1, stale: false, source_ref_ids: [], target_ref_ids: [], ...extra,
})
const relations = Array.from({ length: 28 }, (_, i) => relation(i))
const endpoints = new Map(relations.flatMap((r, i) => [[r.source_note_id, { x: 180, y: 100 + i * 8 }], [r.target_note_id, { x: 720, y: 130 + i * 8 }]] as const))
const noteBooks = new Map(relations.flatMap((r, i) => [[r.source_note_id, `book-a-${i % 7}`], [r.target_note_id, `book-b-${i % 7}`]]))

it('limits a dense course pair to four vines while all relations remain accessible', () => {
  render(<svg><TreeVines relations={relations} endpoints={endpoints} noteBooks={noteBooks} zoom={.8} onRelation={vi.fn()} /></svg>)
  expect(document.querySelectorAll('.kt-vine')).toHaveLength(4)
  fireEvent.click(screen.getAllByRole('button', { name: /查看课程甲与课程乙的/ })[0])
  expect(screen.getByRole('dialog', { name: '藤蔓上的知识联系' })).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /源\d+.*目标\d+/ }).length).toBeGreaterThan(0)
})

it('activates the exact selected relation even when its group is dense', () => {
  const onRelation = vi.fn()
  render(<svg><TreeVines relations={relations} endpoints={endpoints} noteBooks={noteBooks} zoom={.8} selectedId="r-27" onRelation={onRelation} /></svg>)
  fireEvent.click(screen.getByRole('button', { name: '查看源27与目标27的模型推断关联' }))
  expect(onRelation).toHaveBeenCalledExactlyOnceWith(relations[27])
})

it('does not paint rejected, stale or unavailable endpoint relations', () => {
  const invalid = [relation(0, { status: 'rejected' }), relation(1, { stale: true }), relation(90), relation(2, { status: 'pending' })]
  const { container } = render(<svg><TreeVines relations={invalid} endpoints={endpoints} zoom={1} onRelation={vi.fn()} /></svg>)
  expect(container.querySelector('.kt-vine')).toBeNull()
})

it('keeps grouping stable when relations reverse direction or arrive in another order', () => {
  const props = { endpoints, noteBooks, zoom: .8, onRelation: vi.fn() }
  const view = render(<svg><TreeVines relations={relations} {...props} /></svg>)
  const before = [...view.container.querySelectorAll('.kt-vine')].map(el => el.getAttribute('data-vine-members'))
  const reversed = [...relations].reverse().map(r => ({ ...r, source_course_id: r.target_course_id, target_course_id: r.source_course_id, source_note_id: r.target_note_id, target_note_id: r.source_note_id }))
  view.rerender(<svg><TreeVines relations={reversed} {...props} /></svg>)
  expect([...view.container.querySelectorAll('.kt-vine')].map(el => el.getAttribute('data-vine-members'))).toEqual(before)
})
