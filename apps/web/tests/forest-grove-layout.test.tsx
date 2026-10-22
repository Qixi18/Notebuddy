import { expect, test } from 'vitest'
import { forestLayout, signature } from '../src/features/tree/layout'
import { arrangeForestGroves, forestTreeFrame } from '../src/features/tree/forestGroveLayout'
import type { ForestCourse } from '../src/features/forest/types'

const courses = Array.from({ length: 6 }, (_, index) => ({ course_id: `course-${index}`, name: `课程${index}`, position: index, semester: 1, level: 'foundation', learning_state: 'learning' })) as ForestCourse[]

test('same-level courses form asymmetric groves with aligned information below the roots', () => {
  const arranged = arrangeForestGroves(forestLayout(courses))
  expect(arrangeForestGroves(forestLayout(courses))).toEqual(arranged)
  for (let start = 0; start < arranged.length; start += 3) {
    const grove = arranged.slice(start, start + 3)
    expect(grove[1].y).toBeLessThan(Math.min(grove[0].y, grove[2].y) - 100)
    expect(Math.abs(grove[0].y - grove[2].y)).toBeGreaterThan(10)
    expect(new Set(grove.map(tree => tree.captionY)).size).toBe(1)
    expect(grove[0].captionY).toBeGreaterThan(Math.max(...grove.map(tree => tree.y)) + 50)
    expect(grove.map(tree => tree.x)).toEqual(grove.map(tree => tree.x).sort((a, b) => a - b))
  }
})

test('appending a course preserves the persisted world positions of existing trees', () => {
  const input = forestLayout(courses.slice(0, 2))
  const saved = Object.fromEntries(input.map(tree => [tree.course.course_id, { x: tree.x, signature: signature(tree.course) }]))
  const before = arrangeForestGroves(input)
  const after = arrangeForestGroves(forestLayout([courses[2], ...courses.slice(0, 2)], saved))
  for (const tree of before) {
    const next = after.find(item => item.course.course_id === tree.course.course_id)!
    expect({ x: next.x, y: next.y }).toEqual({ x: tree.x, y: tree.y })
  }
})

test('fit and focus frames contain the full caption and its course actions', () => {
  const tree = arrangeForestGroves(forestLayout(courses.slice(0, 3)))[1]
  const points = forestTreeFrame(tree, { x: -290, y: -760, width: 610, height: 825 })
  expect(Math.min(...points.map(point => point.y))).toBeLessThanOrEqual(tree.y - 760)
  expect(Math.max(...points.map(point => point.y))).toBeGreaterThanOrEqual(tree.captionY! + 160)
})
