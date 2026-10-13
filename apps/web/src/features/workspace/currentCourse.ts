import type { Course } from '../../types'

/**
 * 悬浮坞的课程落点。
 *
 * 参考项目的悬浮坞带「全局知识库」兜底——任何上下文里都能提问，落不到具体对象时
 * 自动退回并在界面上说明原因。NoteBuddy 的会话是按课程组织的（
 * POST /courses/:id/conversations），没有跨课程检索，所以这里用
 * 「URL 课程 → 最近访问过的课程 → 课程列表第一门」这条链做等价兜底：
 * 悬浮球在任何页面都能提问，而不是给一个点不动的输入框。
 */

const visitedKey = (courseId: string) => `notebuddy.course.${courseId}.lastVisited`

/** 某门课程的最近访问时间戳；没有记录或记录损坏时返回 0（视为从未访问）。 */
export function courseVisitedAt(courseId: string, read: (key: string) => string | null): number {
  const parsed = Date.parse(read(visitedKey(courseId)) ?? '')
  return Number.isFinite(parsed) ? parsed : 0
}

/**
 * 没有 URL 课程时该用哪门课。最近访问过的优先，其次退回列表第一门。
 * read 注入是为了让这个函数可单测，不直接依赖 localStorage。
 */
export function pickFallbackCourseId(
  courses: Course[],
  visitedAt: (courseId: string) => number,
): string | undefined {
  if (courses.length === 0) return undefined
  let best = courses[0]
  let bestAt = visitedAt(best.id)
  for (const course of courses.slice(1)) {
    const at = visitedAt(course.id)
    if (at > bestAt) {
      best = course
      bestAt = at
    }
  }
  return best.id
}

/** 侧边栏「答疑桌宠」与悬浮坞共用：URL 课程优先，否则落到最近访问的课程。 */
export function resolveConversationCourseId(
  urlCourseId: string | undefined,
  courses: Course[],
  read: (key: string) => string | null,
): string | undefined {
  return urlCourseId ?? pickFallbackCourseId(courses, (id) => courseVisitedAt(id, read))
}
