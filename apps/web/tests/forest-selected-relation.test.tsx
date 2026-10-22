import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { ForestRelationsPanel } from '../src/features/forest/ForestRelationsPanel'
import type { CrossCourseRelation } from '../src/features/forest/types'

afterEach(cleanup)
it('shows the clicked relation first with its exact explanation and two real note links', () => {
  const relations = [0, 1].map(i => ({ id: `r${i}`, source_course_id: 'a', target_course_id: 'b', source_note_id: `a-${i}`, target_note_id: `b-${i}`, source_title: `源${i}`, target_title: `目标${i}`, status: 'confirmed', origin: 'ai', relation_type: 'related', reason: `具体依据${i}`, source_ref_ids: [], target_ref_ids: [] } as unknown as CrossCourseRelation))
  render(<ForestRelationsPanel relations={relations} selectedRelationId="r1" courses={[]} onChange={vi.fn()} onClose={vi.fn()} />)
  expect(screen.getAllByRole('heading', { level: 3 })[0].textContent).toContain('源1')
  const selected = screen.getAllByRole('heading', { level: 3 })[0].closest('article')!
  expect(selected.textContent).toContain('具体依据1')
  expect([...selected.querySelectorAll('a')].map(link => link.getAttribute('href'))).toEqual(['/courses/a/notes/a-1', '/courses/b/notes/b-1'])
})
