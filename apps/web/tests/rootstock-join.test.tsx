import { expect, test } from 'vitest'
import { notebookGeometry, pointAt, tangentAt, rootstockJoin } from '../src/features/tree/naturalBranchGeometry'

test.each([1, 2, 3] as const)('%i notebook branches join the rootstock without changing the existing crown', count => {
  for (const variant of [0, 1, 2] as const) for (let lane = 0; lane < count; lane++) {
    const branch = notebookGeometry({ id: `book-${lane}`, title: '笔记本', treeSlot: lane, notes: [{ id: `note-${lane}`, title: '知识点', treeSlot: 0 }] }, variant, count)
    const before = structuredClone(branch)
    const join = rootstockJoin(branch.primary)
    expect(pointAt(join.curves, 1)).toEqual(pointAt(branch.primary.curves, 0))
    const a = tangentAt(join.curves, 1), b = tangentAt(branch.primary.curves, 0)
    expect(a.x * b.x + a.y * b.y).toBeCloseTo(1, 12)
    expect(join.tipRadius).toBe(branch.primary.rootRadius)
    expect(pointAt(join.curves, 0).y).toBeGreaterThan(-180)
    expect(branch).toEqual(before)
  }
})

test.each([1.36, 2.08, 4.25, 12.88])('expanded branches at scale %f still start inside the common stock', scale => {
  const branch = notebookGeometry({ id: 'book', title: '笔记本', treeSlot: 1, notes: [] }, 2, 3)
  const pivot = branch.primary.curves[0][0].y
  const join = rootstockJoin(branch.primary, scale)
  const toWorld = (point: { x: number; y: number }) => ({ x: point.x, y: pivot + (point.y - pivot) * scale })
  expect(toWorld(pointAt(join.curves, 0)).y).toBeCloseTo(-165, 10)
  expect(toWorld(pointAt(join.curves, 1))).toEqual(pointAt(branch.primary.curves, 0))
  for (let t = 0; t <= 1; t += .05) expect(toWorld(pointAt(join.curves, t)).y).toBeLessThanOrEqual(-164.999)
})
