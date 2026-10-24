import type { ForestCourse } from '../forest/types'

export const HOME_COURSE_LIMIT = 3

/** Learning status is authoritative; visits and old scene snapshots never enroll courses. */
export function selectHomeCourses(courses: ForestCourse[]): ForestCourse[] {
  return courses.filter(course => course.learning_state === 'learning')
    .sort((a, b) => a.position - b.position || a.course_id.localeCompare(b.course_id))
    .slice(0, HOME_COURSE_LIMIT)
}
