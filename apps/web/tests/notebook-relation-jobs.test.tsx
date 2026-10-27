import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { useNotebookRelationJobs } from '../src/features/forest/useNotebookRelationJobs'
import type { ForestJob } from '../src/features/forest/types'

vi.mock('../src/api', () => ({ api: { getLatestForestJob: vi.fn(), getForestJob: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

test('a late discovery cannot replace a newly tracked retry with the previous failed state', async () => {
  let resolve!: (job: ForestJob) => void
  vi.mocked(api.getLatestForestJob).mockReturnValue(new Promise(done => { resolve = done }))
  const refresh = vi.fn().mockResolvedValue([])
  const refreshDirectories = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() => useNotebookRelationJobs('course-a', 0, refresh, refreshDirectories))
  await waitFor(() => expect(api.getLatestForestJob).toHaveBeenCalledWith('course-a'))
  const retried: ForestJob = { id: 'job-1', kind: 'notebook_relations', status: 'pending', progress: 0, error_message: null }
  act(() => result.current.track('course-a', retried))
  await act(async () => { resolve({ ...retried, status: 'failed', error_message: 'previous failure' }) })
  expect(result.current.jobs['course-a'].status).toBe('pending')
})
