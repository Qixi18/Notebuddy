import type { AssetProcessingJob, AssetResource, Coverage, DeletionPreview, Job, Material, Page, PageEvidence, UploadResponse, WebSource } from '../types'
import { request } from './http'

export const materialApi = {
  listNotebookAssets: (notebookId: string) => request<AssetResource[]>(`/api/v1/notebooks/${notebookId}/assets`),
  uploadNotebookAsset: (notebookId: string, file: File) => {
    const body = new FormData(); body.append('file', file)
    return request<{ asset: AssetResource; processing_job: AssetProcessingJob | null }>(`/api/v1/notebooks/${notebookId}/assets`, { method: 'POST', body })
  },
  useAssetInline: (notebookId: string, assetId: string) => request<AssetResource>(`/api/v1/notebooks/${notebookId}/assets/${assetId}/inline`, { method: 'POST' }),
  listNotebookAssetJobs: (notebookId: string, assetId: string) => request<AssetProcessingJob[]>(`/api/v1/notebooks/${notebookId}/assets/${assetId}/processing-jobs`),
  retryAssetParse: (assetId: string) => request<AssetProcessingJob>(`/api/v1/assets/${assetId}/parse-retries`, { method: 'POST' }),
  listNotebookFiles: (notebookId: string) => request<Material[]>(`/api/v1/notebooks/${notebookId}/files`),
  listMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/materials`),
  listDeletedMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/deleted-materials`),
  previewMaterialDeletion: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}/deletion-preview`),
  deleteMaterial: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}`, { method: 'DELETE' }),
  restoreMaterial: (id: string) => request<Material>(`/api/v1/materials/${id}/restore`, { method: 'POST' }),
  uploadMaterial: (courseId: string, file: File, lectureTitle: string, notebookId: string, topicTitle = '', allowDuplicate = false, idempotencyKey = crypto.randomUUID()) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lecture_title', lectureTitle)
    form.append('topic_title', topicTitle)
    form.append('allow_duplicate', String(allowDuplicate))
    form.append('notebook_id', notebookId)
    return request<UploadResponse>(`/api/v1/courses/${courseId}/materials`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: form,
    })
  },
  uploadNotebookFile: (notebookId: string, file: File, lectureTitle = file.name, topicTitle = '', allowDuplicate = false, idempotencyKey = crypto.randomUUID()) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lecture_title', lectureTitle)
    form.append('topic_title', topicTitle)
    form.append('allow_duplicate', String(allowDuplicate))
    return request<UploadResponse>(`/api/v1/notebooks/${notebookId}/files`, {
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
