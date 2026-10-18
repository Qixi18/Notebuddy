import type { Course } from '../../types'

export function selectHomeCourses(courses: Course[]): Course[] {
  return [...courses].sort((a, b) => (b.last_opened_at ?? b.created_at).localeCompare(a.last_opened_at ?? a.created_at) || a.id.localeCompare(b.id)).slice(0, 3)
}
