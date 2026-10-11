import type { Notebook, NotebookSection } from '../../types'
import type { Camera, ForestCourse } from './types'

export type TreePosition = { course: ForestCourse; x: number; y: number; seed: number }
export type SavedSlot = { x: number; signature: string }
export const TREE_SPACING = 470
export function hashId(id: string): number {
  let hash = 2166136261
  for (const char of id) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619)
  return hash >>> 0
}
export const signature = (course: ForestCourse) => `${course.semester}:${course.position}`
export function forestLayout(
  courses: ForestCourse[],
  saved: Record<string, SavedSlot> = {},
): TreePosition[] {
  const sorted = [...courses].sort(
    (a, b) =>
      (a.semester ?? 99) - (b.semester ?? 99) ||
      a.position - b.position ||
      a.course_id.localeCompare(b.course_id),
  )
  const heights = { foundation: 790, professional: 705, application: 610, unspecified: 750 }
  const reordered = sorted.some(
    (course) => saved[course.course_id] && saved[course.course_id].signature !== signature(course),
  )
  const slots = reordered ? {} : saved
  const occupied = sorted
    .filter((c) => slots[c.course_id]?.signature === signature(c))
    .map((c) => slots[c.course_id].x)
  return sorted.map((course, index) => {
    const seed = hashId(course.course_id)
    const old = slots[course.course_id]
    let x = old?.signature === signature(course) ? old.x : 280 + index * TREE_SPACING
    if (old?.signature !== signature(course)) {
      while (occupied.some((position) => Math.abs(position - x) < TREE_SPACING * 0.85))
        x += TREE_SPACING
      occupied.push(x)
    }
    return { course, x, y: heights[course.level] + (seed % 33) - 16, seed }
  })
}
export function visibleCourses(
  trees: TreePosition[],
  camera: Camera,
  width: number,
  adjacent = 1,
): string[] {
  const left = -camera.x / camera.k - TREE_SPACING * adjacent
  const right = (width - camera.x) / camera.k + TREE_SPACING * adjacent
  return trees
    .filter((tree) => tree.x + 220 >= left && tree.x - 220 <= right)
    .map((tree) => tree.course.course_id)
}
export type ForestLeaf = {
  section: NotebookSection
  chapterId: string
  chapterTitle: string
  x: number
  y: number
  angle: number
}
export function treeLeaves(
  book: Notebook,
  expanded?: Set<string>,
  endpoints: Set<string> = new Set(),
): ForestLeaf[] {
  const chapters = [
    ...book.chapters,
    ...(book.historical_sections.length
      ? [{ id: 'history', title: '历史整理', sections: book.historical_sections }]
      : []),
  ]
  const all = chapters.flatMap((chapter, index) =>
    chapter.sections.map((section, sectionIndex) => ({
      section,
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      index,
      sectionIndex,
      total: chapter.sections.length,
    })),
  )
  const selected = expanded
    ? all.filter((item) => expanded.has(item.chapterId))
    : (() => {
        const overview: typeof all = []
        const largest = Math.max(0, ...chapters.map((chapter) => chapter.sections.length))
        for (let round = 0; round < largest && overview.length < 12; round++) {
          for (const chapter of chapters) {
            const item = all.find(
              (leaf) => leaf.chapterId === chapter.id && leaf.sectionIndex === round,
            )
            if (item) overview.push(item)
            if (overview.length === 12) break
          }
        }
        return overview
      })()
  const selectedIds = new Set(selected.map((leaf) => leaf.section.id))
  selected.push(
    ...all.filter((leaf) => endpoints.has(leaf.section.id) && !selectedIds.has(leaf.section.id)),
  )
  const leaves = selected.map((item) => {
    const row = Math.floor(item.index / 2)
    const seed = hashId(item.section.id)
    const baseY = -245 - row * 95
    const localIndex = item.section.section_order ?? item.sectionIndex
    const side = (item.index + Math.floor(localIndex / 4)) % 2 === 0 ? -1 : 1
    const tier = Math.floor(localIndex / 8)
    const column = localIndex % 4
    return {
      section: item.section,
      chapterId: item.chapterId,
      chapterTitle: item.chapterTitle,
      x: side * (63 + column * 44 + (seed % 7)),
      y: baseY - column * 23 - tier * 96,
      angle: side * (18 + (seed % 24)),
    }
  })
  // Keep the overview's first leaves anchored. Later leaves, including temporary
  // relation endpoints, occupy the nearest free cell rather than blocking them.
  const placed: ForestLeaf[] = []
  for (const leaf of leaves) {
    const side = leaf.x < 0 ? -1 : 1
    let position: { x: number; y: number } | undefined
    for (let row = 0; row <= placed.length + 1 && !position; row++) {
      for (const offset of [0, side * 48, -side * 48, side * 96, -side * 96]) {
        const candidate = { x: leaf.x + offset, y: leaf.y - row * 62 }
        if (Math.abs(candidate.x) > 220) continue
        if (
          placed.some(
            (other) => Math.abs(other.x - candidate.x) < 44 && Math.abs(other.y - candidate.y) < 56,
          )
        )
          continue
        position = candidate
        break
      }
    }
    placed.push({ ...leaf, ...position })
  }
  return placed
}
