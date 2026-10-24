import type { Course, NotebookSummary } from '../types'
import { request } from './http'

export const courseApi = {
  listCourses: () => request<Course[]>('/api/v1/courses'),
  listDeletedCourses: () => request<Course[]>('/api/v1/courses/deleted'),
  restoreCourse: (id: string) => request<Course>(`/api/v1/courses/${id}/restore`, { method: 'POST' }),
  listDeletedNotebooks: () => request<NotebookSummary[]>('/api/v1/notebooks/deleted'),
  restoreDeletedNotebook: (notebookId: string, courseId: string) => request<NotebookSummary>(`/api/v1/notebooks/${notebookId}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ course_id: courseId }),
  }),
  createCourse: (name: string, description?: string) => request<Course>('/api/v1/courses', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description: description || null }),
  }),
}
