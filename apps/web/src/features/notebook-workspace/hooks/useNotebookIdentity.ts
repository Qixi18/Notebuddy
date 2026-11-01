import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { notebookApiAdapter } from '../adapters/notebookApiAdapter'

/**
 * 把两条历史路由（``/courses/:courseId/notebooks/:notebookId`` 与
 * ``/notebooks/unbound/:notebookId``）归一成同一个 Workspace 身份。
 *
 * 未分类 Notebook 用 ``courseId: null`` 表达，不再用字符串 ``'unbound'``
 * 冒充课程 ID；``unbound`` 只保留在本地草稿键命名空间里。
 */
export function useNotebookIdentity() {
  const { courseId: routeCourseId, notebookId } = useParams<{ courseId?: string; notebookId?: string }>()
  const isUnbound = !routeCourseId
  const courseId: string | null = routeCourseId ?? null
  const identity = useMemo(
    () => (courseId
      ? { kind: 'course' as const, courseId, notebookId: notebookId ?? '' }
      : { kind: 'unbound' as const, notebookId: notebookId ?? '' }),
    [courseId, notebookId],
  )
  const api = useMemo(() => notebookApiAdapter(identity), [identity])
  return { identity, isUnbound, courseId, notebookId, api }
}
