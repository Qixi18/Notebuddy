import type { Course, CourseOverview, DeletionPreview, NotebookSummary } from '../types'
import { request } from './http'

export type DeletedNotebookSummary = Omit<NotebookSummary, 'course_id'> & { course_id: string | null }

export const courseApi = {
  listCourses: () => request<Course[]>('/api/v1/courses'),
  getCourseOverview: (courseId: string) => request<CourseOverview>(`/api/v1/courses/${courseId}/overview`),
  listDeletedCourses: () => request<Course[]>('/api/v1/courses/deleted'),
  previewCourseDeletion: (id: string) => request<DeletionPreview>(`/api/v1/courses/${id}/deletion-preview`),
  deleteCourse: (id: string) => request<DeletionPreview>(`/api/v1/courses/${id}`, { method: 'DELETE' }),
  restoreCourse: (id: string) => request<Course>(`/api/v1/courses/${id}/restore`, { method: 'POST' }),
  listDeletedNotebooks: () => request<DeletedNotebookSummary[]>('/api/v1/notebooks/deleted'),
  restoreDeletedNotebook: (notebookId: string, courseId: string | null) => request<NotebookSummary>(`/api/v1/notebooks/${notebookId}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ course_id: courseId }),
  }),
  createCourse: (name: string, description?: string) => request<Course>('/api/v1/courses', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description: description || null }),
  }),
  renameCourse: (id: string, name: string) => request<Course>(`/api/v1/courses/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }),
}
