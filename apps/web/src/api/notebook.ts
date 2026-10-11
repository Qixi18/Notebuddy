import type { Note, Notebook } from '../types'
import { request } from './http'

export const notebookApi = {
  getNotebook: (courseId: string) => request<Notebook>(`/api/v1/courses/${courseId}/notebook`),
  getChapter: (courseId: string, materialId: string) => request<{ material_id: string; sections: Note[] }>(`/api/v1/courses/${courseId}/notebook/chapters/${materialId}`),
  reorderChapters: (courseId: string, materialIds: string[], expectedRevision: number) => request<Notebook>(`/api/v1/courses/${courseId}/notebook/order`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_ids: materialIds, expected_order_revision: expectedRevision }),
  }),
}
