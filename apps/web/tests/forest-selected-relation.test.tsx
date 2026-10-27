import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ForestRelationsPanel } from '../src/features/forest/ForestRelationsPanel'
import type { NotebookRelation } from '../src/features/forest/types'

afterEach(cleanup)
it('shows the selected Notebook relation first with two current body links', () => {
  const relations = [0, 1].map(i => ({
    id: `r${i}`, source_course_id: 'a', target_course_id: 'b',
    source_notebook_id: 'book-a', target_notebook_id: 'book-b',
    source_block_id: `a-${i}`, target_block_id: `b-${i}`,
    source_title: `源${i}`, target_title: `目标${i}`,
    source_course_name: '课程 A', target_course_name: '课程 B',
    relation_type: 'related', reason: `具体依据${i}`, created_at: '',
  } satisfies NotebookRelation))
  render(<MemoryRouter><ForestRelationsPanel relations={relations} selectedRelationId="r1" courses={[]}
    onChanged={vi.fn()} onClose={vi.fn()} /></MemoryRouter>)
  expect(screen.getAllByRole('heading', { level: 3 })[0].textContent).toContain('源1')
  const selected = screen.getAllByRole('heading', { level: 3 })[0].closest('article')!
  expect(selected.textContent).toContain('具体依据1')
  expect([...selected.querySelectorAll('a')].map(link => link.getAttribute('href'))).toEqual([
    '/courses/a/notebooks/book-a?section=a-1', '/courses/b/notebooks/book-b?section=b-1',
  ])
})
