import type { Note, Notebook, NotebookDocument, NotebookDocumentBlock, NotebookRead, NotebookSummary } from '../types'
import { request } from './http'

export const notebookApi = {
  listNotebooks: (courseId: string) => request<NotebookSummary[]>(`/api/v1/courses/${courseId}/notebooks`),
  createNotebook: (courseId: string, title: string) => request<NotebookSummary>(`/api/v1/courses/${courseId}/notebooks`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookById: (courseId: string, notebookId: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`),
  getNotebookChapter: (courseId: string, notebookId: string, materialId: string) => request<{ material_id: string; sections: Note[] }>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/chapters/${materialId}`),
  renameNotebook: (courseId: string, notebookId: string, title: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookDocument: (courseId: string, notebookId: string) => request<NotebookDocument>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/document`),
  saveNotebookDocument: (courseId: string, notebookId: string, blocks: NotebookDocumentBlock[], expectedRevision: number) => request<NotebookDocument>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/document`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks, expected_revision: expectedRevision }),
  }),
  visitCourse: (courseId: string) => request<{ last_opened_at: string }>(`/api/v1/courses/${courseId}/visit`, { method: 'POST' }),
  getNotebook: (courseId: string) => request<Notebook>(`/api/v1/courses/${courseId}/notebook`),
}
