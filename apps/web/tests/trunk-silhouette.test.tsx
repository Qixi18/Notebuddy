import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HomeCourseTree } from '../src/features/home/HomeCourseTree'
import { courseCanopyGeometry, forestCanopyGeometry } from '../src/features/tree/courseCanopyGeometry'
import { notebookGeometry as overviewGeometry } from '../src/features/tree/treeGeometry'
import { notebookGeometry, pointAt, radiusAt, tangentAt } from '../src/features/tree/naturalBranchGeometry'
import type { NotebookRead } from '../src/types'

afterEach(cleanup)
const books = (count: number): NotebookRead[] => Array.from({ length: count }, (_, i) => ({
  id: `book-${i}`, title: `笔记本${i}`, course_id: 'course', tree_slot: i,
  order_revision: 0, chapters: [], historical_sections: [], removed_chapters: [],
}))

test.each([1, 2, 3])('%i notebooks grow from one continuous trunk in home and forest', count => {
  const data = books(count)
  const home = courseCanopyGeometry('course', data)
  const forest = forestCanopyGeometry('course', data.map(overviewGeometry), new Set(), '')
  for (const canopy of [home, forest]) for (const { branch } of canopy.items) {
    // The renderer and interaction geometry must share the actual parent trunk.
    expect(branch.primary.parentId).toBeTruthy()
    const trunk = branch.trunk
    expect(trunk).toBeDefined()
    const at = pointAt(trunk.curves, branch.primary.parentT)
    expect(pointAt(branch.primary.curves, 0)).toEqual(at)
    const a = tangentAt(trunk.curves, branch.primary.parentT)
    const b = tangentAt(branch.primary.curves, 0)
    expect(a.x * b.x + a.y * b.y).toBeCloseTo(1, 10)
    expect(branch.primary.rootRadius).toBeLessThanOrEqual(radiusAt(trunk, branch.primary.parentT))
  }
  const view = render(<HomeCourseTree courseId="course" books={data} previewId="preview" onPreview={vi.fn()} onLeave={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  expect(view.container.querySelectorAll('[data-growth-trunk]')).toHaveLength(1)
  expect(view.container.querySelectorAll('[data-trunk-join]')).toHaveLength(0)
})

test('one, two and three leaders have distinct trunk silhouettes and staggered forks', () => {
  const canopies = [1, 2, 3].map(count => courseCanopyGeometry('course', books(count)))
  const trunks = canopies.map(canopy => canopy.items[0].branch.trunk)
  expect(trunks.every(Boolean)).toBe(true)
  expect(new Set(trunks.map(trunk => trunk.outline)).size).toBe(3)
  const attachments = canopies[2].items.map(item => item.branch.primary.parentT)
  expect(new Set(attachments).size).toBe(3)
})

test.each([0, 1, 2] as const)('root variant %i supports all three branch counts without gaps or thicker collars', variant => {
  for (const count of [1, 2, 3] as const) for (let lane=0; lane<count; lane++) {
    const { trunk, primary } = notebookGeometry({ id: `book-${lane}`, treeSlot: lane, title: '笔记本', notes: [] }, variant, count)
    expect(pointAt(primary.curves, 0)).toEqual(pointAt(trunk.curves, primary.parentT))
    const a=tangentAt(trunk.curves, primary.parentT), b=tangentAt(primary.curves, 0)
    expect(a.x*b.x+a.y*b.y).toBeCloseTo(1, 10)
    expect(primary.rootRadius).toBeLessThanOrEqual(radiusAt(trunk, primary.parentT))
    if (primary.parentT===1) expect(primary.rootRadius).toBe(trunk.tipRadius)
  }
})

test('tall forest banks keep the parent tangent in world coordinates', () => {
  const canopy=forestCanopyGeometry('course',books(6).map(overviewGeometry),new Set(),'')
  for (const { branch, scaleY=1 } of canopy.items) {
    const a=tangentAt(branch.trunk.curves,branch.primary.parentT)
    const local=tangentAt(branch.primary.curves,0)
    const length=Math.hypot(local.x,local.y*scaleY)
    expect((a.x*local.x+a.y*local.y*scaleY)/length).toBeCloseTo(1,10)
    const origin=pointAt(branch.primary.curves,0)
    expect(origin).toEqual(pointAt(branch.trunk.curves,branch.primary.parentT))
  }
})
