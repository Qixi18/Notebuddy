import type {
  DocNode, Note, Notebook, NotebookAttachment, NotebookDocumentResponse, NotebookRead,
  NotebookEditSuggestion, NotebookRevision, NotebookRevisionSummary, NotebookSummary,
  NotebookGenerationJob,
  NotebookUploadBatch,
} from '../types'
import { request } from './http'

export type UnboundNotebookSummary = {
  id: string; title: string; created_at: string; updated_at: string; cover_url?: string | null
}

export const notebookApi = {
  listNotebookEditSuggestions: (notebookId: string) => request<NotebookEditSuggestion[]>(`/api/v1/notebooks/${encodeURIComponent(notebookId)}/edit-suggestions`),
  reviewNotebookEditSuggestion: (notebookId: string, suggestionId: string, decision: 'accept' | 'reject', expectedRevision: number, selectedOperationIndices?: number[]) => request<NotebookDocumentResponse>(`/api/v1/notebooks/${encodeURIComponent(notebookId)}/edit-suggestions/${encodeURIComponent(suggestionId)}/review`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, expected_revision: expectedRevision, ...(selectedOperationIndices ? { selected_operation_indices: selectedOperationIndices } : {}) }),
  }),
  getNotebookBlockSources: (notebookId: string, blockId: string) => request<Array<{
    asset_name: string; quote: string; page_number: number; parse_run_id: string; status: string
  }>>(`/api/v1/notebooks/${encodeURIComponent(notebookId)}/blocks/${encodeURIComponent(blockId)}/sources`),
  getNotebookSections: (courseId: string, notebookId: string) => request<Array<{
    block_id: string; heading: string; level: number; order: number; revision: number; excerpt: string
  }>>(`/api/v1/courses/${courseId}/notebooks/${notebookId}/sections`),
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
  moveNotebook: (notebookId: string, courseId: string) => request<NotebookSummary>(`/api/v1/notebooks/${notebookId}/move`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ course_id: courseId }),
  }),
  uploadNotebookCover: (notebookId: string, file: File) => {
    const body = new FormData(); body.append('file', file)
    return request<{ cover_url: string }>(`/api/v1/notebooks/${notebookId}/cover`, { method: 'PUT', body })
  },
  deleteNotebookCover: (notebookId: string) => request<void>(`/api/v1/notebooks/${notebookId}/cover`, { method: 'DELETE' }),
  deleteNotebook: (courseId: string, notebookId: string) => request<void>(`/api/v1/courses/${courseId}/notebooks/${notebookId}`, { method: 'DELETE' }),
  listDeletedNotebooks: () => request<NotebookSummary[]>('/api/v1/notebooks/deleted'),
  restoreDeletedNotebook: (notebookId: string, courseId: string) => request<NotebookSummary>(`/api/v1/notebooks/${notebookId}/restore`, {
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
  createNotebookGenerationJob: async (notebookId: string, assetIds: string[] = []) => request<NotebookGenerationJob>(`/api/v1/notebooks/${notebookId}/generation-jobs`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': await generationKey(notebookId, assetIds) },
    body: JSON.stringify({ asset_ids: assetIds }),
  }),
  getNotebookGenerationJob: (notebookId: string, jobId: string) => request<NotebookGenerationJob>(`/api/v1/notebooks/${notebookId}/generation-jobs/${jobId}`),
  listNotebookGenerationJobs: (notebookId: string) => request<NotebookGenerationJob[]>(`/api/v1/notebooks/${notebookId}/generation-jobs`),
  listNotebookUploadBatches: (notebookId: string) => request<NotebookUploadBatch[]>(`/api/v1/notebooks/${notebookId}/upload-batches`),
  getNotebookUploadBatch: (notebookId: string, batchId: string) => request<NotebookUploadBatch>(`/api/v1/notebooks/${notebookId}/upload-batches/${batchId}`),
  closeNotebookUploadBatch: (notebookId: string, batchId: string) => request<NotebookUploadBatch>(`/api/v1/notebooks/${notebookId}/upload-batches/${batchId}/complete`, { method: 'POST' }),
  cancelNotebookGenerationJob: (notebookId: string, jobId: string) => request<NotebookGenerationJob>(`/api/v1/notebooks/${notebookId}/generation-jobs/${jobId}/cancel`, { method: 'POST' }),
  retryNotebookGenerationJob: (notebookId: string, jobId: string) => request<NotebookGenerationJob>(`/api/v1/notebooks/${notebookId}/generation-jobs/${jobId}/retry`, { method: 'POST' }),
}

async function generationKey(notebookId: string, assetIds: string[]): Promise<string> {
  const value = new TextEncoder().encode(`${notebookId}:${[...new Set(assetIds)].sort().join(',')}`)
  const digest = await crypto.subtle.digest('SHA-256', value)
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `notebook-input-${hex}`
}
