import type { ForestCourse } from '../forest/types'

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
