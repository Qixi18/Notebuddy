import type { NotebookRead } from '../../types'
import { hashId } from './layout'
import { notebookGeometry, overviewBranches, overviewLeaves, type KnowledgeLeaf, type NotebookGeometry } from './treeGeometry'
import { notebookGeometry as naturalNotebook, rotate, type BookGeometry } from './naturalBranchGeometry'

export type CanopyItem = { book: NotebookRead; branch: BookGeometry; leaves: KnowledgeLeaf[]; transform?: string; scaleY?: number }
export type CourseCanopy = { items: CanopyItem[]; variant: 0 | 1 | 2; bounds: { x: number; y: number; width: number; height: number } }

export function homePreviewBooks(books: NotebookRead[], selectedBookId?: string) {
  const preview = books.slice(0, 3)
  const selected = books.find(book => book.id === selectedBookId)
  if (selected && !preview.includes(selected)) preview.splice(2, 1, selected)
  return preview
}

/** The same authored natural crown is used in home and the forest canvas. */
export function courseCanopyGeometry(courseId: string, books: NotebookRead[], selectedBookId?: string) {
  const preview = homePreviewBooks(books, selectedBookId)
  return buildCanopy(courseId, preview.map((book, index) => ({ book, index, leaves: notebookGeometry(book).leaves.slice(0, 6) })))
}

export function forestCanopyGeometry(courseId: string, branches: NotebookGeometry[], pins: Set<string>, search: string, expandedBookId?: string): CourseCanopy {
  return buildCanopy(courseId, overviewBranches(branches, pins, search).map(source => ({ book: source.book, index: branches.indexOf(source), leaves: overviewLeaves(source, pins, search, source.book.id === expandedBookId) })))
}

/** The notebook count selects a complete one-, two- or three-leader silhouette. */
function buildCanopy(courseId: string, sources: { book: NotebookRead; index: number; leaves: KnowledgeLeaf[] }[]): CourseCanopy {
  const variant = hashId(courseId) % 3 as 0 | 1 | 2
  const items: CanopyItem[] = []
  let left = -270, right = 270, top = sources.length ? -490 : -510
  for (const source of sources) {
    const { book, index } = source
    const crownSize = Math.min(3, sources.length) as 1 | 2 | 3
    const lane = index % 3
    const originals = source.leaves
    const banks = Math.max(1, Math.ceil(originals.length / 6))
    for (let bank = 0; bank < banks; bank++) {
      const batch = originals.slice(bank * 6, bank * 6 + 6)
      const branch = naturalNotebook({ id: book.id, title: book.title, treeSlot: lane, notes: batch.map((leaf, slot) => ({ id: leaf.section.id, title: leaf.section.title, treeSlot: slot })) }, variant, crownSize)
      const scale = 1 + Math.floor(index / 3) * .65 + bank * .36
      const pivot = branch.primary.curves[0][0].y
      const transform = scale === 1 ? undefined : `translate(0,${pivot * (1 - scale)}) scale(1,${scale})`
      const leaves = branch.leaves.map((leaf, slot) => {
        const stem = { x: leaf.petiole.x, y: pivot + (leaf.petiole.y - pivot) * scale }
        const rotatedPetiole = rotate({ x: 0, y: 3 }, leaf.angle)
        const point = { x: stem.x - rotatedPetiole.x, y: stem.y - rotatedPetiole.y }
        left = Math.min(left, point.x - 76); right = Math.max(right, point.x + 76); top = Math.min(top, point.y - 95)
        return { ...batch[slot], ...point, stem, angle: leaf.angle, variant: [0, 1, 2, 1, 0, 3][leaf.variant] }
      })
      for (const limb of branch.limbs) for (const curve of limb.curves) for (const point of curve) {
        left = Math.min(left, point.x - 20); right = Math.max(right, point.x + 20); top = Math.min(top, pivot + (point.y - pivot) * scale - 20)
      }
      items.push({ book, branch, leaves, transform, scaleY: scale })
    }
  }
  return { items, variant, bounds: { x: left, y: top, width: right - left, height: 65 - top } }
}
