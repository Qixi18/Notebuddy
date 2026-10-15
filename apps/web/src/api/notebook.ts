import type { Note, Notebook, NotebookRead, NotebookSummary, NotebookReadingPosition, ReadingPositionUpdate } from '../types'
import { request } from './http'

export const notebookApi = {
  listNotebooks: (courseId: string) => request<NotebookSummary[]>(`/api/v1/courses/${courseId}/notebooks`),
  createNotebook: (courseId: string, title: string) => request<NotebookSummary>(`/api/v1/courses/${courseId}/notebooks`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookById: (courseId: string, notebookId: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`),
  renameNotebook: (courseId: string, notebookId: string, title: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookChapter: (courseId: string, notebookId: string, materialId: string) => request<{ material_id: string; sections: Note[] }>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/chapters/${materialId}`),
  reorderNotebookChapters: (courseId: string, notebookId: string, materialIds: string[], expectedRevision: number) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/order`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ material_ids: materialIds, expected_order_revision: expectedRevision }),
  }),
  getReadingPosition: (courseId: string, notebookId: string) => request<NotebookReadingPosition | null>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/reading-position`),
  saveReadingPosition: (courseId: string, notebookId: string, position: ReadingPositionUpdate) => request<NotebookReadingPosition>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/reading-position`, {
    method: 'PUT', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(position),
  }),
  visitCourse: (courseId: string) => request<{ last_opened_at: string }>(`/api/v1/courses/${courseId}/visit`, { method: 'POST' }),
  getNotebook: (courseId: string) => request<Notebook>(`/api/v1/courses/${courseId}/notebook`),
  getChapter: (courseId: string, materialId: string) => request<{ material_id: string; sections: Note[] }>(`/api/v1/courses/${courseId}/notebook/chapters/${materialId}`),
  reorderChapters: (courseId: string, materialIds: string[], expectedRevision: number) => request<Notebook>(`/api/v1/courses/${courseId}/notebook/order`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_ids: materialIds, expected_order_revision: expectedRevision }),
  }),
}
