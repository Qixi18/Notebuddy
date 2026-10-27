import type { AssetDocument, AssetProcessingJob, AssetResource, Coverage, DeletionPreview, DocumentBlock, DocumentCoverage, DocumentParseRunSummary, Job, Material, Page, PageEvidence, UploadResponse, WebSource } from '../types'
import { request } from './http'

export const materialApi = {
  listNotebookAssets: (notebookId: string) => request<AssetResource[]>(`/api/v1/notebooks/${notebookId}/assets`),
  listDetachedNotebookAssets: (notebookId: string) => request<AssetResource[]>(`/api/v1/notebooks/${notebookId}/detached-assets`),
  uploadNotebookAsset: (notebookId: string, file: File, batchId?: string) => {
    const body = new FormData(); body.append('file', file)
    return request<{ asset: AssetResource; processing_job: AssetProcessingJob | null; upload_batch_id?: string }>(`/api/v1/notebooks/${notebookId}/assets`, {
      method: 'POST', headers: batchId ? { 'X-Upload-Batch-ID': batchId } : undefined, body,
    })
  },
  useAssetInline: (notebookId: string, assetId: string) => request<AssetResource>(`/api/v1/notebooks/${notebookId}/assets/${assetId}/inline`, { method: 'POST' }),
  removeNotebookAsset: (notebookId: string, assetId: string) => request<{ asset_id: string; state: string }>(`/api/v1/notebooks/${notebookId}/assets/${assetId}`, { method: 'DELETE' }),
  restoreNotebookAsset: (notebookId: string, assetId: string) => request<AssetResource>(`/api/v1/notebooks/${notebookId}/assets/${assetId}/restore`, { method: 'POST' }),
  listNotebookAssetJobs: (notebookId: string, assetId: string) => request<AssetProcessingJob[]>(`/api/v1/notebooks/${notebookId}/assets/${assetId}/processing-jobs`),
  retryAssetParse: (assetId: string) => request<AssetProcessingJob>(`/api/v1/assets/${assetId}/parse-retries`, { method: 'POST' }),
  listNotebookFiles: (notebookId: string) => request<Material[]>(`/api/v1/notebooks/${notebookId}/files`),
  listMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/materials`),
  listDeletedMaterials: (courseId: string) => request<Material[]>(`/api/v1/courses/${courseId}/deleted-materials`),
  previewMaterialDeletion: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}/deletion-preview`),
  deleteMaterial: (id: string) => request<DeletionPreview>(`/api/v1/materials/${id}`, { method: 'DELETE' }),
  restoreMaterial: (id: string) => request<Material>(`/api/v1/materials/${id}/restore`, { method: 'POST' }),
  uploadMaterial: (courseId: string, file: File, lectureTitle: string, notebookId: string, topicTitle = '', allowDuplicate = false, idempotencyKey = crypto.randomUUID(), batchId?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lecture_title', lectureTitle)
    form.append('topic_title', topicTitle)
    form.append('allow_duplicate', String(allowDuplicate))
    form.append('notebook_id', notebookId)
    return request<UploadResponse>(`/api/v1/courses/${courseId}/materials`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey, ...(batchId ? { 'X-Upload-Batch-ID': batchId } : {}) }, body: form,
    })
  },
  uploadNotebookFile: (notebookId: string, file: File, lectureTitle = file.name, topicTitle = '', allowDuplicate = false, idempotencyKey = crypto.randomUUID(), batchId?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lecture_title', lectureTitle)
    form.append('topic_title', topicTitle)
    form.append('allow_duplicate', String(allowDuplicate))
    return request<UploadResponse>(`/api/v1/notebooks/${notebookId}/files`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey, ...(batchId ? { 'X-Upload-Batch-ID': batchId } : {}) }, body: form,
    })
  },
  getJob: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`),
  getLatestMaterialJob: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/latest-job`),
  listMaterialWebSources: (materialId: string) => request<WebSource[]>(`/api/v1/materials/${materialId}/web-sources`),
  retryMaterial: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/retry`, { method: 'POST' }),
  listPages: (materialId: string) => request<Page[]>(`/api/v1/materials/${materialId}/pages`),
  getPageEvidence: (materialId: string, pageNumber: number) => request<PageEvidence>(`/api/v1/materials/${materialId}/pages/${pageNumber}/evidence`),
  getCoverage: (materialId: string) => request<Coverage>(`/api/v1/materials/${materialId}/coverage`),
  listAssetParseRuns: (assetId: string, notebookId: string) => request<DocumentParseRunSummary[]>(`/api/v1/assets/${assetId}/parse-runs?notebook_id=${encodeURIComponent(notebookId)}`),
  getAssetDocument: (assetId: string, notebookId: string, runId?: string) => request<AssetDocument>(
    `/api/v1/assets/${assetId}/document${runId ? `/runs/${encodeURIComponent(runId)}` : ''}?notebook_id=${encodeURIComponent(notebookId)}`,
  ),
  getAssetPageEvidence: (assetId: string, notebookId: string, pageNumber: number, runId?: string) => request<DocumentBlock[]>(
    `/api/v1/assets/${assetId}/document/pages/${pageNumber}/evidence?notebook_id=${encodeURIComponent(notebookId)}${runId ? `&run_id=${encodeURIComponent(runId)}` : ''}`,
  ),
  getAssetCoverage: (assetId: string, notebookId: string, runId?: string) => request<DocumentCoverage>(
    `/api/v1/assets/${assetId}/document/coverage?notebook_id=${encodeURIComponent(notebookId)}${runId ? `&run_id=${encodeURIComponent(runId)}` : ''}`,
  ),
  assetPageRenderUrl: (assetId: string, notebookId: string, pageNumber: number, runId?: string) =>
    `/api/v1/assets/${assetId}/document/pages/${pageNumber}/render?notebook_id=${encodeURIComponent(notebookId)}${runId ? `&run_id=${encodeURIComponent(runId)}` : ''}`,
  reparseMaterial: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/reparse`, { method: 'POST' }),
  requestOCR: (materialId: string) => request<Job>(`/api/v1/materials/${materialId}/ocr`, { method: 'POST' }),
}
