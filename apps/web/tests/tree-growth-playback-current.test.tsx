import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { growthLedger } from '../src/features/tree/growth/ledger'
import { useGrowthPlayback } from '../src/features/tree/growth/useGrowthPlayback'
import type { CourseTree } from '../src/types'

const tree = (sections: string[]): CourseTree => ({
  course_id: 'playback-course',
  notebooks: [{
    id: 'book', course_id: 'playback-course', title: 'Book', tree_slot: 0,
    chapters: [{ id: 'chapter', sections: sections.map(blockId => ({
      id: `row-${blockId}`, block_id: blockId, title: blockId,
    })) }], historical_sections: [], removed_chapters: [],
  }],
}) as CourseTree

afterEach(() => {
  cleanup()
  sessionStorage.clear()
})

test('a covered forest holds a new block until the dialog closes', async () => {
  sessionStorage.clear()
  const { result, rerender } = renderHook(({ directory }) =>
    useGrowthPlayback([directory], ['playback-course'], ['playback-course']), {
    initialProps: { directory: tree(['old-block']) },
  })
  const dialog = document.createElement('div')
  dialog.setAttribute('role', 'dialog')
  document.body.append(dialog)
  rerender({ directory: tree(['old-block', 'new-block']) })
  await waitFor(() => expect(growthLedger.pending().some(event => event.id === 'new-block')).toBe(true))
  expect(result.current.sections.size).toBe(0)
  act(() => dialog.remove())
  await waitFor(() => expect(result.current.sections.has(JSON.stringify(['book', 'new-block']))).toBe(true))
  expect(growthLedger.pending()).toEqual([])
})
