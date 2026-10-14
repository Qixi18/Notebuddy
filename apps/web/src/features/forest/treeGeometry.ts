import type { NotebookRead, SectionRead } from '../../types'
import { hashId } from './layout'
import type { Camera } from './types'

export const BOTANICAL_SPACING = 620
export type Point = { x: number; y: number }
export type KnowledgeLeaf = Point & {
  section: SectionRead; chapterId: string | null; chapterTitle: string
  angle: number; variant: number; stem: Point
}
export type NotebookGeometry = {
  book: NotebookRead; anchor: Point; origin: Point; side: number
  spine: string; leaves: KnowledgeLeaf[]
}

// Persisted slots, never chapter order or array indices, place branches and leaves.
export function notebookGeometry(book: NotebookRead): NotebookGeometry {
  const slot = book.tree_slot
  const side = slot % 2 === 0 ? -1 : 1
  const tier = Math.floor(slot / 2)
  const anchor = { x: side * (122 + (hashId(book.id) % 19)), y: -325 - tier * 155 - (slot % 2) * 68 }
  const origin = { x: 4 + side * 8, y: -195 - Math.min(tier, 3) * 64 - (slot % 2) * 50 }
  const sections = [
    ...book.chapters.filter(chapter => !chapter.deleted_at).flatMap(chapter => chapter.sections.map(section => ({ section, chapterId: chapter.id, chapterTitle: chapter.title }))),
    ...book.historical_sections.map(section => ({ section, chapterId: null, chapterTitle: '历史整理' })),
  ]
  const seen = new Set<string>()
  const leaves = sections.filter(({ section }) => {
    if (seen.has(section.id) || section.notebook_id !== book.id) return false
    seen.add(section.id)
    return true
  }).sort((a, b) => a.section.tree_slot - b.section.tree_slot).map(item => {
    const leafSlot = item.section.tree_slot
    const index = leafSlot % 6
    const bank = Math.floor(leafSlot / 6)
    const leafSide = index % 2 === 0 ? -1 : 1
    const stem = { x: anchor.x + side * (index * 5 + bank * 40), y: anchor.y - index * 28 - bank * 185 }
    return { ...item, stem, x: stem.x + leafSide * 32, y: stem.y - 24, angle: leafSide * (32 + hashId(item.section.id) % 19), variant: hashId(item.section.id) % 6 }
  })
  return { book, anchor, origin, side, leaves, spine: `M${origin.x},${origin.y} C${side * 47},${origin.y - 20} ${anchor.x - side * 23},${anchor.y + 61} ${anchor.x},${anchor.y} C${anchor.x + side * 16},${anchor.y - 46} ${anchor.x + side * 29},${anchor.y - 103} ${anchor.x + side * 29},${anchor.y - 151}` }
}
export function overviewBranches(books: NotebookGeometry[], pins: Set<string>, search: string) {
  return books.filter((book, index) => index < 6 || book.leaves.some(leaf => pins.has(leaf.section.id) || (search && leaf.section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()))))
}
export function overviewLeaves(branch: NotebookGeometry, pins: Set<string>, search: string, expanded = false) {
  const limit = expanded ? 24 : 6
  const normal = branch.leaves.slice(0, limit)
  const matches = branch.leaves.filter(leaf => search && leaf.section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase())).slice(0, 6)
  const temporary = branch.leaves.filter(leaf => !normal.includes(leaf) && (pins.has(leaf.section.id) || matches.includes(leaf)))
  // The persistent slot still identifies the physical leaf. A temporary compact
  // lens brings selected distant banks to the overview without moving existing
  // leaves; closing the selection removes only these extra leaves.
  return [...normal, ...temporary.map((leaf, index) => {
    const lensSlot = limit + index
    const column = lensSlot % 6
    const bank = Math.floor(lensSlot / 6)
    const leafSide = column % 2 === 0 ? -1 : 1
    const stem = { x: branch.anchor.x + branch.side * (column * 5 + bank * 40), y: branch.anchor.y - column * 28 - bank * 185 }
    return { ...leaf, stem, x: stem.x + leafSide * 32, y: stem.y - 24 }
  })]
}
export function sceneInitialCamera(count: number, width: number, height: number): Camera & { visibleCount: number } {
  const visibleCount = Math.min(Math.max(1, count), width >= 1600 ? 3 : width >= 760 ? 2 : 1)
  const k = Math.min(1.15, Math.max(0.35, Math.min((width - 36) / (visibleCount * BOTANICAL_SPACING), (height - 82) / 780)))
  return { visibleCount, k, x: (width - visibleCount * BOTANICAL_SPACING * k) / 2, y: height - 62 - 790 * k }
}
export function fitPoints(points: Point[], width: number, height: number, padding = 75): Camera {
  if (!points.length) return sceneInitialCamera(1, width, height)
  const left = Math.min(...points.map(point => point.x)) - padding
  const right = Math.max(...points.map(point => point.x)) + padding
  const top = Math.min(...points.map(point => point.y)) - padding
  const bottom = Math.max(...points.map(point => point.y)) + padding
  const k = Math.max(.02, Math.min(1.35, width / Math.max(1, right - left), height / Math.max(1, bottom - top)))
  return { k, x: width / 2 - (left + right) / 2 * k, y: height / 2 - (top + bottom) / 2 * k }
}
