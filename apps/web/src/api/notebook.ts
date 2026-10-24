import type {
  DocNode, Note, Notebook, NotebookAttachment, NotebookDocumentResponse, NotebookRead,
  NotebookRevision, NotebookRevisionSummary, NotebookSummary,
} from '../types'
import { request } from './http'

export type UnboundNotebookSummary = {
  id: string; title: string; created_at: string; updated_at: string
}

export const notebookApi = {
  listUnboundNotebooks: () => request<UnboundNotebookSummary[]>('/api/v1/notebooks/unbound'),
  createUnboundNotebook: (title: string) => request<UnboundNotebookSummary>('/api/v1/notebooks/unbound', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getUnboundNotebook: (notebookId: string) => request<UnboundNotebookSummary>(`/api/v1/notebooks/unbound/${notebookId}`),
  renameUnboundNotebook: (notebookId: string, title: string) => request<UnboundNotebookSummary>(`/api/v1/notebooks/unbound/${notebookId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getUnboundNotebookDocument: (notebookId: string) => request<NotebookDocumentResponse>(`/api/v1/notebooks/unbound/${notebookId}/document`),
  saveUnboundNotebookDocument: (notebookId: string, content: DocNode, expectedRevision: number) => request<NotebookDocumentResponse>(`/api/v1/notebooks/unbound/${notebookId}/document`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schema_version: 2, content, expected_revision: expectedRevision }),
  }),
  uploadUnboundNotebookAttachment: (notebookId: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<NotebookAttachment>(`/api/v1/notebooks/${notebookId}/attachments`, { method: 'POST', body })
  },
  listUnboundNotebookRevisions: (notebookId: string) => request<NotebookRevisionSummary[]>(`/api/v1/notebooks/${notebookId}/revisions`),
  getUnboundNotebookRevision: (notebookId: string, revision: number) => request<NotebookRevision>(`/api/v1/notebooks/${notebookId}/revisions/${revision}`),
  restoreUnboundNotebookRevision: (notebookId: string, revision: number, expectedRevision: number) => request<NotebookDocumentResponse>(`/api/v1/notebooks/${notebookId}/revisions/${revision}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: expectedRevision }),
  }),
  bindNotebook: (notebookId: string, courseId: string) => request<NotebookSummary>(`/api/v1/notebooks/${notebookId}/bind`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ course_id: courseId }),
  }),
  unbindNotebook: (notebookId: string) => request<UnboundNotebookSummary>(`/api/v1/notebooks/${notebookId}/unbind`, { method: 'POST' }),
  listNotebooks: (courseId: string) => request<NotebookSummary[]>(`/api/v1/courses/${courseId}/notebooks`),
  createNotebook: (courseId: string, title: string) => request<NotebookSummary>(`/api/v1/courses/${courseId}/notebooks`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookById: (courseId: string, notebookId: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`),
  getNotebookChapter: (courseId: string, notebookId: string, materialId: string) => request<{ material_id: string; sections: Note[] }>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/chapters/${materialId}`),
  renameNotebook: (courseId: string, notebookId: string, title: string) => request<NotebookRead>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  getNotebookDocument: (courseId: string, notebookId: string) => request<NotebookDocumentResponse>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/document`),
  saveNotebookDocument: (courseId: string, notebookId: string, content: DocNode, expectedRevision: number) => request<NotebookDocumentResponse>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/document`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schema_version: 2, content, expected_revision: expectedRevision }),
  }),
  uploadNotebookAttachment: (courseId: string, notebookId: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<NotebookAttachment>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/attachments`, {
      method: 'POST', body,
    })
  },
  listNotebookRevisions: (courseId: string, notebookId: string) => request<NotebookRevisionSummary[]>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/revisions`),
  getNotebookRevision: (courseId: string, notebookId: string, revision: number) => request<NotebookRevision>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/revisions/${revision}`),
  restoreNotebookRevision: (courseId: string, notebookId: string, revision: number, expectedRevision: number) => request<NotebookDocumentResponse>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/revisions/${revision}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: expectedRevision }),
  }),
  visitCourse: (courseId: string) => request<{ last_opened_at: string }>(`/api/v1/courses/${courseId}/visit`, { method: 'POST' }),
  getNotebook: (courseId: string) => request<Notebook>(`/api/v1/courses/${courseId}/notebook`),
}
