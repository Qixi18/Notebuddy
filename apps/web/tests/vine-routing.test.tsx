import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { buildVine, vinePoint, type Cubic, type Point } from '../src/features/tree/vineGeometry'
import { TreeVines } from '../src/features/tree/TreeVines'
import { courseCanopyGeometry } from '../src/features/tree/courseCanopyGeometry'
import { sceneBlockId } from '../src/features/forest/notebookRelations'
import type { TreeRelation } from '../src/features/forest/types'
import type { NotebookRead } from '../src/types'

afterEach(cleanup)
const stone = { x: 350, y: 315, width: 300, height: 180 }
function overlaps(point: Point, rect = stone, padding = 0) {
  return point.x > rect.x - padding && point.x < rect.x + rect.width + padding
    && point.y > rect.y - padding && point.y < rect.y + rect.height + padding
}
function polyPoints(path: string): Point[] {
  const values = path.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  return Array.from({ length: values.length / 2 }, (_, i) => ({ x: values[i * 2], y: values[i * 2 + 1] }))
}
function curvesFromPath(path: string): Cubic[] {
  const points = polyPoints(path), curves: Cubic[] = []
  for (let i = 1; i < points.length; i += 3) curves.push([points[i - 1], points[i], points[i + 1], points[i + 2]])
  return curves
}

it('reroutes the full vine paint and its 44px stem target above stones without changing grafts or relation IDs', () => {
  const input = { id: 'across-stone', order: 0, start: { x: 0, y: 0 }, end: { x: 1000, y: 50 },
    midpoint: { x: 500, y: 400 }, relationIds: ['real-ai-relation'], routeExclusions: [{ rect: stone }] }
  const vine = buildVine(input)
  expect(vinePoint(vine.curves, 0)).toEqual(input.start)
  expect(vinePoint(vine.curves, 1)).toEqual(input.end)
  expect(vine.leaves.map(leaf => leaf.relationId)).toEqual(input.relationIds)
  for (let i = 0; i <= 1000; i++) expect(overlaps(vinePoint(vine.curves, i / 1000), stone, 8)).toBe(false)
  for (const tendril of vine.tendrils) for (const point of polyPoints(tendril)) expect(overlaps(point, stone, 2)).toBe(false)
  for (const scale of [.35, .8, 1.6]) {
    for (const point of polyPoints(vine.hit.centerline)) expect(overlaps(point, stone, 22 / scale)).toBe(false)
  }
})

it.each([.35, .8, 1.6])('keeps a real three-tree route out of the middle root bed and stone at %s zoom', zoom => {
  const ids = ['a', 'b', 'c']
  const books = ids.map(id => ({ id: `book-${id}`, course_id: id, tree_slot: 0,
    title: `笔记${id}`, chapters: [], historical_sections: [{ id: `note-${id}`, block_id: `note-${id}`, notebook_id: `book-${id}`, title: `知识${id}`, tree_slot: 0 }],
  })) as NotebookRead[]
  const geometry = new Map(ids.map((id, i) => [id, { x: i * 600, y: i === 1 ? 600 : 700,
    grove: 0, canopy: courseCanopyGeometry(id, [books[i]]) }]))
  const relation = { id: 'real-across', source_course_id: 'a', target_course_id: 'c',
    source_notebook_id: 'book-a', target_notebook_id: 'book-c',
    source_block_id: sceneBlockId('book-a', 'note-a'), target_block_id: sceneBlockId('book-c', 'note-c'),
    source_course_name: '课程a', target_course_name: '课程c',
    source_title: '知识a', target_title: '知识c', status: 'confirmed', stale: false, origin: 'ai', relation_type: 'related', reason: '课程关系', created_at: '',
  } as TreeRelation
  const endpoints = new Map([[sceneBlockId('book-a', 'note-a'), { x: 100, y: 300 }], [sceneBlockId('book-c', 'note-c'), { x: 1100, y: 300 }]])
  const noteBooks = new Map([[sceneBlockId('book-a', 'note-a'), 'book-a'], [sceneBlockId('book-c', 'note-c'), 'book-c']])
  const rootAndStone = { x: 250, y: 515, width: 700, height: 300 }
  const { container } = render(<svg><TreeVines relations={[relation]} endpoints={endpoints} noteBooks={noteBooks}
    courseGeometry={geometry} layout="grove" zoom={zoom} onRelation={vi.fn()}
    leafExclusions={[{ rect: rootAndStone }]} /></svg>)
  const action = container.querySelector('[data-vine-members="real-across"]')!
  expect(action).toBeTruthy()
  const curves = curvesFromPath(action.querySelector('.vine-focus')!.getAttribute('d')!)
  for (let i = 0; i <= 1000; i++) expect(overlaps(vinePoint(curves, i / 1000), rootAndStone, 8)).toBe(false)
})
