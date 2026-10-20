import { expect, test } from 'vitest'
import { auditTree, buildTree, pointAt, type TreeInput } from '../src/features/tree/naturalBranchGeometry'

const input: TreeInput = { id: 'course', variant: 0, books: Array.from({ length: 3 }, (_, b) => ({ id: `book-${b}`, treeSlot: b, title: '笔记本', notes: Array.from({ length: 6 }, (_, n) => ({ id: `${b}-note-${n}`, treeSlot: n, title: '知识点' })) })) }
test.each([0, 1, 2] as const)('natural crown %s connects every fork and rotated leaf with independent click space', variant => {
  const value = { ...input, variant }
  const tree = buildTree(value), audit = auditTree(tree)
  expect(audit.leafCount).toBe(18)
  expect(audit.limbCount).toBe(30)
  expect(audit.maxJoinError).toBeLessThan(1e-7)
  expect(audit.maxPetioleError).toBeLessThan(1e-7)
  expect(audit.minLeafDistance).toBeGreaterThan(75)
  expect(tree.books[2].primary.curves[0][0]).toEqual(tree.books[0].primary.curves[0][0])
  for (const book of tree.books) {
    expect(book.limbs.some(limb => limb.level === 2)).toBe(true)
    expect(book.limbs.some(limb => limb.level === 3)).toBe(true)
    for (const limb of book.limbs) {
      expect(limb.rootRadius).toBeGreaterThan(limb.tipRadius)
      expect(limb.outline).not.toMatch(/NaN|Infinity/)
      const tip = pointAt(limb.curves, 1)
      expect(tip.x).toBeGreaterThan(tree.bounds.x)
      expect(tip.x).toBeLessThan(tree.bounds.x + tree.bounds.width)
    }
  }
  expect(buildTree(value)).toEqual(tree)
  const extra = structuredClone(value)
  extra.books[0].notes.pop()
  expect(buildTree(extra).books[1]).toEqual(tree.books[1])
})
