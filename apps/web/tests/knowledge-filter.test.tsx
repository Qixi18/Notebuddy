import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { CourseKnowledgeStructure } from '../src/pages/CourseKnowledgeStructure'
import { api } from '../src/api'

const state = vi.hoisted(() => ({ workspace: {} as Record<string, unknown> }))
vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => state.workspace, featurePath: () => '/materials' }))
vi.mock('../src/api', () => ({ api: {
  getNoteSources: vi.fn().mockResolvedValue([]), getNoteWebSources: vi.fn().mockResolvedValue([]),
  listKnowledgeProposals: vi.fn().mockResolvedValue([]), listKnowledgeChanges: vi.fn().mockResolvedValue([]),
} }))
afterEach(cleanup)

test('lecture filtering hides other occurrences of a shared concept', async () => {
  state.workspace = {
    course: { name: 'Course' }, notes: [
      { id: 'n1', knowledge_node_id: 'k', content_markdown: 'Lecture 1 body' },
      { id: 'n2', knowledge_node_id: 'k', content_markdown: 'Lecture 2 body' },
    ], courseContentLoading: false,
    materials: [{ id: 'm1', lecture_title: 'Lecture 1' }, { id: 'm2', lecture_title: 'Lecture 2' }],
    graph: { nodes: [{ id: 'k', name: 'Matrix', sources: [], summary: '' }], edges: [], occurrences: [
      { id: 'n1', material_id: 'm1', knowledge_node_id: 'k', title: 'Matrix' },
      { id: 'n2', material_id: 'm2', knowledge_node_id: 'k', title: 'Matrix' },
    ] },
  }
  render(<MemoryRouter initialEntries={['/courses/c']}><Routes><Route path="/courses/:courseId" element={<CourseKnowledgeStructure />} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm2' } })
  const tree = within(screen.getByRole('tree'))
  expect(tree.queryByRole('treeitem', { name: /Lecture 1/ })).toBeNull()
  expect(tree.getAllByRole('treeitem', { name: /Lecture 2/ })).toHaveLength(2)
  await waitFor(() => expect(api.getNoteSources).toHaveBeenCalledWith('n2'))
})
