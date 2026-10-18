import type { Coverage, DeletionPreview, Job, Material, Page, PageEvidence, UploadResponse, WebSource } from '../types'
import { request } from './http'

export const materialApi = {
  listMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/materials`),
  listDeletedMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/deleted-materials`),
  previewMaterialDeletion: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}/deletion-preview`),
  deleteMaterial: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}`, { method: 'DELETE' }),
  restoreMaterial: (id: string) => request<Material>(`/api/v1/materials/${id}/restore`, { method: 'POST' }),
  uploadMaterial: (courseId: string, file: File, lectureTitle: string, topicTitle = '', allowDuplicate = false, idempotencyKey = crypto.randomUUID(), notebookId?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lecture_title', lectureTitle)
    form.append('topic_title', topicTitle)
    form.append('allow_duplicate', String(allowDuplicate))
    if (notebookId) form.append('notebook_id', notebookId)
    return request<UploadResponse>(`/api/v1/courses/${courseId}/materials`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: form,
    })
  },
  getJob: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`),
  getLatestMaterialJob: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/latest-job`),
  listMaterialWebSources: (materialId: string) => request<WebSource[]>(`/api/v1/materials/${materialId}/web-sources`),
  retryMaterial: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/retry`, { method: 'POST' }),
  listPages: (materialId: string) => request<Page[]>(`/api/v1/materials/${materialId}/pages`),
  getPageEvidence: (materialId: string, pageNumber: number) => request<PageEvidence>(`/api/v1/materials/${materialId}/pages/${pageNumber}/evidence`),
  getCoverage: (materialId: string) => request<Coverage>(`/api/v1/materials/${materialId}/coverage`),
  reparseMaterial: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/reparse`, { method: 'POST' }),
  requestOCR: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/ocr`, { method: 'POST' }),
}
