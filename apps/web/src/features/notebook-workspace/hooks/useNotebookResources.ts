import { useCallback, useEffect, useMemo, useState, type RefObject } from 'react'

import { api } from '../../../api'
import type {
  AssetProcessingBudget, AssetProcessingJob, AssetResource, DeletionPreview, Material,
  NotebookAttachment,
} from '../../../types'
import type { NotebookEditorHandle } from '../../notebook-editor/NotebookEditor'

type NotebookApi = ReturnType<typeof import('../adapters/notebookApiAdapter').notebookApiAdapter>

/**
 * Notebook 的资料资源边界：课程资料、原始图片资产、来源预览、可恢复项与文件预算展示。
 *
 * 课程与未分类 Notebook 走同一套资源体验（路线图 §5.2 第 3 条）：未分类只是没有
 * 课程资料列表，图片资产、移除/恢复、预算展示都一致。
 */
export function useNotebookResources({
  notebookId, courseId, isUnbound, loaded, materials, refreshCurrentMaterials,
  notebookApi, editorRef, onNotice, processingRoute,
}: {
  notebookId?: string
  courseId: string | null
  isUnbound: boolean
  loaded: boolean
  materials: Material[]
  refreshCurrentMaterials: () => Promise<unknown>
  notebookApi: NotebookApi
  editorRef: RefObject<NotebookEditorHandle | null>
  onNotice: (message: string) => void
  processingRoute?: 'standard' | 'llm'
}) {
  const [assetResources, setAssetResources] = useState<AssetResource[]>([])
  const [detachedAssetResources, setDetachedAssetResources] = useState<AssetResource[]>([])
  const [assetResourcesLoaded, setAssetResourcesLoaded] = useState(false)
  const [deletedBookMaterials, setDeletedBookMaterials] = useState<Material[]>([])
  const [materialRemoval, setMaterialRemoval] = useState<{ id: string; impact: DeletionPreview }>()
  const [materialActionError, setMaterialActionError] = useState<string>()
  const [materialBusyId, setMaterialBusyId] = useState<string>()
  const [assetJobs, setAssetJobs] = useState<Record<string, AssetProcessingJob>>({})
  const [fileBudgets, setFileBudgets] = useState<Record<string, AssetProcessingBudget>>({})
  const [assetUploadError, setAssetUploadError] = useState<string>()
  const [imageError, setImageError] = useState<string>()
  const [assetRemoval, setAssetRemoval] = useState<AssetResource>()

  const refreshAssetResources = useCallback(async () => {
    if (!notebookId) return
    const [rows, detached] = await Promise.all([
      api.listNotebookAssets(notebookId),
      api.listDetachedNotebookAssets(notebookId),
    ])
    setAssetResources(rows)
    setDetachedAssetResources(detached)
  }, [notebookId])

  useEffect(() => {
    if (!loaded || !notebookId) return
    let active = true
    void Promise.all([api.listNotebookAssets(notebookId), api.listDetachedNotebookAssets(notebookId)]).then(([rows, detached]) => {
      if (active) { setAssetResources(rows); setDetachedAssetResources(detached); setAssetResourcesLoaded(true) }
    }).catch((cause: unknown) => {
      if (active) { setAssetUploadError(cause instanceof Error ? cause.message : '资源列表读取失败'); setAssetResourcesLoaded(true) }
    })
    return () => { active = false }
  }, [loaded, notebookId])

  const bookMaterials = useMemo(
    () => materials.filter((material) => material.notebook_id === notebookId),
    [materials, notebookId],
  )
  const sourceImages = useMemo(() => assetResources.filter(
    (asset) => asset.role === 'source_material' && asset.media_type === 'image',
  ), [assetResources])

  const budgetAssetIds = useMemo(() => Array.from(new Set([
    ...bookMaterials.map(item => item.asset_id), ...assetResources.map(item => item.id),
  ].filter((id): id is string => Boolean(id)))), [assetResources, bookMaterials])

  /* 预算展示跟随生成状态刷新：解析/生成每个阶段都可能改变已用额度。 */
  useEffect(() => {
    if (!notebookId || !budgetAssetIds.length) { setFileBudgets({}); return }
    let active = true
    void Promise.all(budgetAssetIds.map(async assetId => {
      try { return [assetId, await api.getAssetProcessingBudget(assetId, notebookId)] as const }
      catch { return null }
    })).then(rows => {
      if (active) setFileBudgets(Object.fromEntries(rows.filter((row): row is NonNullable<typeof row> => row !== null)))
    })
    return () => { active = false }
  }, [budgetAssetIds, notebookId])

  /* 图片资产的上传后处理状态：2.5s 轮询，直到任务结束。 */
  useEffect(() => {
    if (!notebookId || assetResources.length === 0) return
    let active = true
    const refresh = () => {
      for (const asset of assetResources.filter((item) => item.media_type === 'image' && item.role === 'source_material')) {
        void api.listNotebookAssetJobs(notebookId, asset.id).then((jobs) => {
          if (!active || !jobs[0]) return
          setAssetJobs((current) => ({ ...current, [asset.id]: jobs[0] }))
        }).catch(() => undefined)
      }
    }
    refresh()
    const timer = window.setInterval(refresh, 2500)
    return () => { active = false; window.clearInterval(timer) }
  }, [assetResources, notebookId])

  /* 可恢复的课程资料：未分类 Notebook 没有课程归属，不请求。 */
  useEffect(() => {
    if (!loaded || isUnbound || !courseId || !notebookId) return
    let active = true
    void api.listDeletedMaterials(courseId).then((items) => {
      if (active) setDeletedBookMaterials(items.filter((item) => item.notebook_id === notebookId))
    }).catch(() => { if (active) setDeletedBookMaterials([]) })
    return () => { active = false }
  }, [courseId, isUnbound, loaded, materials, notebookId])

  async function prepareMaterialRemoval(material: Material) {
    if (materialBusyId) return
    setMaterialActionError(undefined)
    setMaterialBusyId(material.id)
    try {
      const impact = await api.previewMaterialDeletion(material.id)
      if (impact.active_jobs) throw new Error('资料仍在处理中，请等待任务结束后再移除。')
      setMaterialRemoval({ id: material.id, impact })
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '读取移除影响失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function confirmMaterialRemoval() {
    if (!materialRemoval) return
    setMaterialBusyId(materialRemoval.id)
    try {
      await api.deleteMaterial(materialRemoval.id)
      setMaterialRemoval(undefined)
      await refreshCurrentMaterials()
      if (courseId) setDeletedBookMaterials((await api.listDeletedMaterials(courseId)).filter((item) => item.notebook_id === notebookId))
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '移除资料失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function restoreBookMaterial(materialId: string) {
    setMaterialBusyId(materialId)
    try {
      await api.restoreMaterial(materialId)
      await refreshCurrentMaterials()
      if (courseId) setDeletedBookMaterials((await api.listDeletedMaterials(courseId)).filter((item) => item.notebook_id === notebookId))
      setMaterialActionError(undefined)
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '恢复资料失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function runMaterialOperation(materialId: string, operation: 'retry' | 'reparse') {
    setMaterialBusyId(materialId)
    setMaterialActionError(undefined)
    try {
      if (operation === 'retry') await api.retryMaterial(materialId)
      else await api.reparseMaterial(materialId)
      await refreshCurrentMaterials()
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '资料处理任务启动失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function removeNotebookAsset(closePreview?: () => void) {
    if (!assetRemoval || !notebookId) return
    setMaterialBusyId(assetRemoval.id)
    setMaterialActionError(undefined)
    try {
      await api.removeNotebookAsset(notebookId, assetRemoval.id)
      setAssetRemoval(undefined)
      await refreshAssetResources()
      closePreview?.()
      onNotice('资源已从当前 Notebook 移除；正文和历史版本中的引用保持不变。')
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '移除资源失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function restoreNotebookAsset(asset: AssetResource) {
    if (!notebookId) return
    setMaterialBusyId(asset.id)
    setMaterialActionError(undefined)
    try {
      await api.restoreNotebookAsset(notebookId, asset.id)
      await refreshAssetResources()
      onNotice('资料已恢复到当前 Notebook。')
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '恢复资料失败')
    } finally { setMaterialBusyId(undefined) }
  }

  async function handleUploadSourceImage(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !notebookId) return
    setAssetUploadError(undefined)
    try {
      const result = await api.uploadNotebookAsset(notebookId, file, undefined, processingRoute)
      await refreshAssetResources()
      onNotice(result.processing_job?.status === 'pending'
        ? `原始图片已保存，${result.asset.processing_route === 'llm' ? 'AI 读取' : '本地解析'}任务已排队。`
        : `原始图片已保存${result.asset.state === 'ready' ? '，等待解析' : ''}。`)
      return result
    } catch (cause) {
      setAssetUploadError(cause instanceof Error ? cause.message : '图片资料上传失败')
      return null
    }
  }

  async function insertSourceAsset(asset: AssetResource) {
    const editor = editorRef.current?.editor
    if (!editor || !notebookId || asset.media_type !== 'image') return
    try {
      const inline = await api.useAssetInline(notebookId, asset.id)
      editor.chain().focus().insertImage({
        // Persist the canonical stable asset URL accepted by document_json.
        // The Notebook-scoped content_url is useful for UI/API responses, but
        // the document contract intentionally stores /api/v1/assets/{id}/content.
        src: `/api/v1/assets/${inline.id}/content`, assetId: inline.id, alt: asset.original_name,
      }).run()
      onNotice('图片已插入正文；保存后会纳入笔记历史版本。')
    } catch (cause) {
      setAssetUploadError(cause instanceof Error ? cause.message : '插入图片失败')
    }
  }

  async function uploadImage(file: File): Promise<{ src: string; attachmentId: string } | null> {
    if (!notebookId) return null
    setImageError(undefined)
    try {
      const attachment: NotebookAttachment = await notebookApi.uploadAttachment(file)
      return { src: attachment.url, attachmentId: attachment.id }
    } catch (cause) {
      setImageError(cause instanceof Error ? cause.message : '图片上传失败')
      return null
    }
  }

  return {
    assetResources, detachedAssetResources, assetResourcesLoaded, deletedBookMaterials,
    materialRemoval, setMaterialRemoval, materialActionError, setMaterialActionError,
    materialBusyId, assetJobs, fileBudgets, assetUploadError, setAssetUploadError,
    imageError, setImageError, assetRemoval, setAssetRemoval,
    refreshAssetResources, bookMaterials, sourceImages, budgetAssetIds,
    prepareMaterialRemoval, confirmMaterialRemoval, restoreBookMaterial, runMaterialOperation,
    removeNotebookAsset, restoreNotebookAsset, handleUploadSourceImage, insertSourceAsset, uploadImage,
  }
}
