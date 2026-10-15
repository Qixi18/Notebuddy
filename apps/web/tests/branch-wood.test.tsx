import { describe, expect, it } from 'vitest'
import { branchWood } from '../src/features/forest/branchWood'
import { notebookGeometry, overviewLeaves } from '../src/features/forest/treeGeometry'
import type { NotebookRead } from '../src/types'

function geometry(slot: number, count: number) {
  const book: NotebookRead = { id: `book-${slot}`, course_id: 'course', title: '笔记本', tree_slot: slot, order_revision: 0, historical_sections: [], removed_chapters: [], chapters: [{ id: 'chapter', title: '第一讲', chapter_order: 0, deleted_at: null, status: 'completed', sections: Array.from({ length: count }, (_, i) => ({ id: `note-${i}`, notebook_id: `book-${slot}`, tree_slot: i, title: '知识点', material_id: 'chapter', knowledge_node_id: 'node', section_key: String(i), section_order: i, user_locked: false, revision_number: 1, updated_at: '' })) }] }
  return notebookGeometry(book)
}

describe('connected tapered branch wood', () => {
  it.each([0, 1, 2, 5, 9])('keeps finite, ordered taper and smooth spine for book slot %s', slot => {
    for (const count of [0, 1, 6, 24]) {
      const branch = geometry(slot, count)
      const wood = branchWood(branch, branch.leaves)
      expect(wood.samples[0].point).toEqual(branch.origin)
      expect(wood.outline).not.toMatch(/NaN|Infinity/)
      for (let i = 0; i < wood.textureSpans.length; i++) {
        const span = wood.textureSpans[i]
        const from = wood.pointAt(i / wood.textureSpans.length), to = wood.pointAt((i + 1) / wood.textureSpans.length)
        const chord = Math.hypot(to.x - from.x, to.y - from.y)
        expect(span.length).toBeGreaterThan(chord)
        const angle = (span.angle - 90) * Math.PI / 180
        expect(Math.cos(angle) * (to.x - from.x) + Math.sin(angle) * (to.y - from.y)).toBeCloseTo(chord)
      }
      for (let i = 0; i < wood.samples.length; i++) {
        const sample = wood.samples[i]
        expect(Number.isFinite(sample.point.x + sample.point.y + sample.width)).toBe(true)
        expect(sample.width).toBeGreaterThan(0)
        if (i) {
          const previous = wood.samples[i - 1]
          expect(sample.width).toBeLessThan(previous.width)
          expect(sample.point.y).toBeLessThan(previous.point.y)
          expect(sample.normal.x * previous.normal.x + sample.normal.y * previous.normal.y).toBeGreaterThan(.75)
        }
      }
    }
  })
  it('attaches each real leaf to a point on the spine, including an expanded bank and distant search lens', () => {
    const branch = geometry(0, 200)
    for (const expanded of [false, true]) {
      const leaves = overviewLeaves(branch, new Set(['note-199']), '', expanded)
      const before = structuredClone(leaves)
      const wood = branchWood(branch, leaves)
      expect(wood.twigs).toHaveLength(leaves.length)
      expect(new Set(wood.twigs.map(twig => `${twig.root.x},${twig.root.y}`)).size).toBe(leaves.length)
      wood.twigs.forEach((twig, i) => {
        expect(twig.root).toEqual(wood.pointAt(twig.position))
        expect(twig.end).toEqual({ x: leaves[i].x, y: leaves[i].y + 3 })
        expect(twig.noteId).toBe(leaves[i].section.id)
        expect(twig.path).not.toMatch(/NaN|Infinity/)
      })
      expect(leaves).toEqual(before)
      expect(branchWood(branch, leaves)).toMatchObject({ outline: wood.outline, bark: wood.bark, twigs: wood.twigs })
    }
  })
})
