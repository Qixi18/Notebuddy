import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { notebookApiAdapter } from '../adapters/notebookApiAdapter'

/** Resolves legacy course and unbound URLs into one workspace identity. */
export function useNotebookIdentity() {
  const { courseId: routeCourseId, notebookId } = useParams<{ courseId?: string; notebookId: string }>()
  const isUnbound = !routeCourseId
  const courseId = routeCourseId ?? 'unbound'
  const api = useMemo(() => notebookApiAdapter(isUnbound
    ? { kind: 'unbound', notebookId: notebookId ?? '' }
    : { kind: 'course', courseId, notebookId: notebookId ?? '' }), [courseId, isUnbound, notebookId])
  return { identity: isUnbound ? { kind: 'unbound' as const, notebookId } : { kind: 'course' as const, courseId, notebookId }, isUnbound, courseId, notebookId, api }
}
