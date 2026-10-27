import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useWorkspace } from '../components/AppLayout'
import type { AssetResource, DeletionPreview, Material, NotebookDocumentResponse, NotebookGenerationJob, NotebookRead, NotebookUploadBatch } from '../types'
import type { AssetProcessingJob } from '../types'
import {
  NotebookEditor, type AIAction, type NotebookEditorHandle, type SelectionAnchor,
} from '../features/notebook-editor/NotebookEditor'
import {
  countText, docToMarkdown, excerptAroundSelection, extractOutline, legacyBlocksToDocument, normalizeDocument, plainText, stableStringify,
  type DocNode,
} from '../features/notebook-editor/document'
import { useNotebookSave } from '../features/notebook-editor/useNotebookSave'
import { clearDraft, readDraft, type NotebookDraft } from '../features/notebook-editor/draftStore'
import { useRegisterNotebookBridge, type NotebookBridgeValue } from '../features/notebook-editor/NotebookBridge'
import { DocumentSourcePreview } from '../features/notebook-editor/DocumentSourcePreview'
import './NotebookPage.css'

function serverDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`)
}

function clock(value?: string): string {
  if (!value) return ''
  const date = serverDate(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[character] as string))
}

export function NotebookPage() {
  const { courseId, notebookId } = useParams<{ courseId: string; notebookId: string }>()
  return <NotebookPageBody key={`${courseId ?? ''}:${notebookId ?? ''}`} />
}

function NotebookPageBody() {
  const { courseId, notebookId } = useParams<{ courseId: string; notebookId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const linkedSectionId = searchParams.get('section')
  const linkedChapterId = searchParams.get('chapter')
  const linkedAssetId = searchParams.get('asset')
  const uploadRequested = searchParams.get('upload') === '1'
  const linkedAssetPage = Number(searchParams.get('page') || 1)
  const { course, materials, busy, uploadMaterial, refreshCurrentMaterials, setDocumentDirty } = useWorkspace()

  const [outline, setOutline] = useState<NotebookRead>()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState<DocNode>({ type: 'doc', content: [] })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string>()
  const [documentWarning, setDocumentWarning] = useState<string>()
  const [uploadError, setUploadError] = useState<string>()
  const [imageError, setImageError] = useState<string>()
  const [titleError, setTitleError] = useState<string>()
  const [resourcesOpen, setResourcesOpen] = useState(true)
  const [directoryOpen, setDirectoryOpen] = useState(true)
  const [activeBlockId, setActiveBlockId] = useState<string>()
  const [titleSaving, setTitleSaving] = useState(false)
  const [selection, setSelection] = useState<SelectionAnchor | null>(null)
  const [editVersion, setEditVersion] = useState(0)
  const [draftFound, setDraftFound] = useState<NotebookDraft | null>(null)
  const [conflictPreview, setConflictPreview] = useState<NotebookDocumentResponse | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [notice, setNotice] = useState<string>()
  const [assetResources, setAssetResources] = useState<AssetResource[]>([])
  const [detachedAssetResources, setDetachedAssetResources] = useState<AssetResource[]>([])
  const [assetResourcesLoaded, setAssetResourcesLoaded] = useState(false)
  const [deletedBookMaterials, setDeletedBookMaterials] = useState<Material[]>([])
  const [materialRemoval, setMaterialRemoval] = useState<{ id: string; impact: DeletionPreview }>()
  const [materialActionError, setMaterialActionError] = useState<string>()
  const [materialBusyId, setMaterialBusyId] = useState<string>()
  const [assetJobs, setAssetJobs] = useState<Record<string, AssetProcessingJob>>({})
  const [assetUploadError, setAssetUploadError] = useState<string>()
  const [allowDuplicateUploads, setAllowDuplicateUploads] = useState(false)
  const [assetRemoval, setAssetRemoval] = useState<AssetResource>()
  const [generationJob, setGenerationJob] = useState<NotebookGenerationJob | null>(null)
  const [generationBusy, setGenerationBusy] = useState(false)
  const [uploadBatchId, setUploadBatchId] = useState<string>()
  const [uploadBatch, setUploadBatch] = useState<NotebookUploadBatch | null>(null)
  const [generationError, setGenerationError] = useState<string>()
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceImageInput = useRef<HTMLInputElement>(null)
  const editorRef = useRef<NotebookEditorHandle>(null)
  const editorReadyRef = useRef(false)
  const pageActiveRef = useRef(true)
  const lastDeepLinkRef = useRef<string | undefined>(undefined)

  const save = useNotebookSave({ courseId, notebookId })

  const insertAI = useCallback((text: string, mode: 'after' | 'replace', anchor: SelectionAnchor | null, expectedRevision?: number, expectedEditVersion?: number) => {
    const handle = editorRef.current
    const editor = handle?.editor
    if (!handle || !editor) return false
    if (expectedRevision !== undefined && expectedRevision !== save.revision) return false
    if (expectedEditVersion !== undefined && expectedEditVersion !== editVersion) return false
    const target = anchor
    if (!target) return false
    if (mode === 'replace') {
      if (!target.text.trim()) return false
      if (editor.state.doc.textBetween(target.from, target.to, '\n') !== target.text) return false
      return handle.replaceRange(text, target.from, target.to)
    }
    if (target.to > editor.state.doc.content.size) return false
    if (editor.state.doc.textBetween(target.from, target.to, '\n') !== target.text) return false
    handle.insertMarkdown(text, target.to)
    return true
  }, [editVersion, save.revision])

  const adoptDocument = useCallback((document: DocNode, revision: number, updatedAt: string, expectedEditVersion: number) => {
    if (editVersion !== expectedEditVersion || save.isDirty() || save.revision !== revision - 1) return false
    const normalized = normalizeDocument(document)
    editorRef.current?.replaceContent(normalized)
    setContent(normalized)
    setEditVersion((value) => value + 1)
    save.reset(normalized, revision, updatedAt)
    return true
  }, [editVersion, save.isDirty, save.reset, save.revision])

  const bridgeValue = useMemo<NotebookBridgeValue | null>(() => courseId && notebookId && loaded ? {
    courseId,
    notebookId,
    title,
    revision: save.revision,
    editVersion,
    excerpt: excerptAroundSelection(content, selection?.text),
    selection,
    insertAI,
    isDirty: save.isDirty,
    adoptDocument,
  } : null, [adoptDocument, content, courseId, editVersion, insertAI, loaded, notebookId, save.isDirty, save.revision, selection, title])
  useRegisterNotebookBridge(bridgeValue)

  useEffect(() => {
    pageActiveRef.current = true
    return () => { pageActiveRef.current = false }
  }, [])

  useEffect(() => {
    if (!courseId || !notebookId) return
    let active = true
    setLoaded(false)
    setLoadError(undefined)
    setOutline(undefined)
    setDocumentWarning(undefined)
    setDraftFound(null)
    setEditVersion(0)
    editorReadyRef.current = false
    void Promise.all([api.getNotebookById(courseId, notebookId), api.getNotebookDocument(courseId, notebookId)])
      .then(async ([nextOutline, document]) => {
        if (!active) return
        const normalized = normalizeDocument(document.content)
        setOutline(nextOutline)
        setTitle(nextOutline.title)
        setContent(normalized)
        setDocumentWarning(document.warning ?? undefined)
        save.reset(normalized, document.revision, document.updated_at)
        setLoaded(true)
        const draft = await readDraft(courseId, notebookId)
        if (active && draft && stableStringify(draft.content) !== stableStringify(normalized)) setDraftFound(draft)
      })
      .catch((cause: unknown) => {
        if (active) setLoadError(cause instanceof Error ? cause.message : '笔记读取失败')
      })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, notebookId])

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

  useEffect(() => {
    if (!uploadRequested || !loaded) return
    fileInput.current?.click()
    const next = new URLSearchParams(searchParams)
    next.delete('upload')
    setSearchParams(next, { replace: true })
  }, [loaded, searchParams, setSearchParams, uploadRequested])

  const closeAssetPreview = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('asset'); next.delete('page')
    setSearchParams(next, { replace: true })
  }

  useEffect(() => {
    if (!loaded || !notebookId) return
    let active = true
    void api.listNotebookUploadBatches(notebookId).then((batches) => {
      if (!active || !batches.length) return
      const current = batches.find((batch) => ['open', 'waiting_parse', 'parsing', 'generating', 'partial_failure'].includes(batch.status)) ?? batches[0]
      setUploadBatch(current)
      setUploadBatchId(current.id)
    }).catch(() => undefined)
    return () => { active = false }
  }, [loaded, notebookId])

  useEffect(() => {
    if (!notebookId || !uploadBatchId || uploadBatch?.status === 'completed') return
    let active = true
    const refresh = async () => {
      try {
        const batch = await api.getNotebookUploadBatch(notebookId, uploadBatchId)
        if (!active) return
        setUploadBatch(batch)
        const generationId = batch.generation_jobs.at(-1)?.id
        if (generationId && generationId !== generationJob?.id) {
          const job = await api.getNotebookGenerationJob(notebookId, generationId)
          if (active) setGenerationJob(job)
        }
      } catch (cause) {
        if (active) setGenerationError(cause instanceof Error ? cause.message : '上传批次状态读取失败')
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [generationJob?.id, notebookId, uploadBatch?.status, uploadBatchId])

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

  useEffect(() => {
    if (!notebookId || !generationJob || !['pending', 'processing', 'cancel_requested'].includes(generationJob.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.getNotebookGenerationJob(notebookId, generationJob.id).then((job) => {
        if (!active) return
        setGenerationJob(job)
        if (job.status === 'completed' && generationJob.status !== 'completed') {
          if (save.isDirty()) {
            setNotice('AI 补充内容已写入服务器。当前有未保存的本地编辑，已保留草稿；保存冲突面板可用于合并服务器版本。')
            return
          }
          void api.getNotebookDocument(courseId!, notebookId).then((latest) => {
            if (!active || save.isDirty() || latest.revision <= save.revision) return
            const normalized = normalizeDocument(latest.content)
            editorRef.current?.replaceContent(normalized)
            setContent(normalized)
            save.reset(normalized, latest.revision, latest.updated_at)
            setNotice('AI 补充内容已追加到正式正文。')
          }).catch(() => setNotice('AI 已完成；正文刷新失败，请手动重新加载页面。'))
        }
      }).catch((cause: unknown) => {
        if (active) setGenerationError(cause instanceof Error ? cause.message : '生成状态读取失败')
      })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [courseId, generationJob?.id, generationJob?.status, notebookId, save.isDirty, save.reset, save.revision])

  const headings = useMemo(() => extractOutline(content), [content])
  const bookMaterials = useMemo(() => materials.filter((material) => material.notebook_id === notebookId), [materials, notebookId])

  useEffect(() => {
    if (!loaded || !courseId || !notebookId) return
    let active = true
    void api.listDeletedMaterials(courseId).then((items) => {
      if (active) setDeletedBookMaterials(items.filter((item) => item.notebook_id === notebookId))
    }).catch(() => { if (active) setDeletedBookMaterials([]) })
    return () => { active = false }
  }, [courseId, loaded, materials, notebookId])

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

  async function removeNotebookAsset() {
    if (!assetRemoval || !notebookId) return
    setMaterialBusyId(assetRemoval.id)
    setMaterialActionError(undefined)
    try {
      await api.removeNotebookAsset(notebookId, assetRemoval.id)
      setAssetRemoval(undefined)
      await refreshAssetResources()
      if (linkedAssetId === assetRemoval.id) closeAssetPreview()
      setNotice('资源已从当前 Notebook 移除；正文和历史版本中的引用保持不变。')
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
      setNotice('资料已恢复到当前 Notebook。')
    } catch (cause) {
      setMaterialActionError(cause instanceof Error ? cause.message : '恢复资料失败')
    } finally { setMaterialBusyId(undefined) }
  }
  const wordCount = useMemo(() => countText(content), [content])
  const dirty = save.state !== 'saved' || title !== (outline?.title ?? '')

  useEffect(() => {
    setDocumentDirty(Boolean(loaded && dirty))
  }, [dirty, loaded, setDocumentDirty])
  useEffect(() => () => setDocumentDirty(false), [setDocumentDirty])

  useEffect(() => {
    if (!loaded) return
    const targetId = linkedSectionId && headings.some((heading) => heading.id === linkedSectionId)
      ? linkedSectionId
      : !linkedSectionId && linkedChapterId
        ? headings.find((heading) => heading.level === 1 && heading.text === outline?.chapters.find((chapter) => chapter.id === linkedChapterId)?.title)?.id
        : undefined
    if (!targetId) return
    const key = `${courseId}:${notebookId}:${linkedSectionId ?? linkedChapterId}:${targetId}`
    if (lastDeepLinkRef.current === key) return
    lastDeepLinkRef.current = key
    window.setTimeout(() => {
      editorRef.current?.focusBlock(targetId)
      setActiveBlockId(targetId)
    }, 120)
  }, [courseId, headings, linkedChapterId, linkedSectionId, loaded, notebookId, outline?.chapters])

  const handleChange = useCallback((doc: DocNode) => {
    if (!editorReadyRef.current) return
    setContent(doc)
    setEditVersion((value) => value + 1)
    save.markEdited(doc)
  }, [save])

  async function renameTitle() {
    const nextTitle = title.trim()
    if (!courseId || !notebookId || !outline || !nextTitle || nextTitle === outline.title || titleSaving) {
      if (!nextTitle) setTitle(outline?.title ?? '')
      return
    }
    setTitleSaving(true)
    setTitleError(undefined)
    try {
      const renamed = await api.renameNotebook(courseId, notebookId, nextTitle)
      setOutline(renamed)
      setTitle((current) => current === nextTitle ? renamed.title : current)
    } catch (cause) {
      setTitleError(cause instanceof Error ? cause.message : '笔记名称保存失败')
    } finally { setTitleSaving(false) }
  }

  async function handleUploadMaterial(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!files.length || !courseId || !notebookId) return
    setUploadError(undefined)
    try {
      const batchId = crypto.randomUUID()
      const results: PromiseSettledResult<unknown>[] = []
      for (const file of files) {
        const lectureTitle = file.name.replace(/\.[^.]+$/, '').trim() || '新资料'
        try {
          results.push({ status: 'fulfilled', value: await uploadMaterial(
            file, lectureTitle, notebookId, '', allowDuplicateUploads, batchId,
          ) })
        } catch (reason) {
          results.push({ status: 'rejected', reason })
        }
      }
      const uploadFailures = results.filter((result) => result.status === 'rejected').length
      await refreshCurrentMaterials()
      setAllowDuplicateUploads(false)
      setOutline(await api.getNotebookById(courseId, notebookId))
      setResourcesOpen(true)
      if (uploadFailures < files.length) {
        const batch = await api.closeNotebookUploadBatch(notebookId, batchId)
        setUploadBatchId(batchId)
        setUploadBatch(batch)
        setNotice(uploadFailures
          ? `${files.length - uploadFailures} 份资料已进入后台处理；${uploadFailures} 份上传失败。关闭页面后后台仍会继续。`
          : `${files.length} 份资料已进入后台处理；解析完成后会自动追加正式正文。`)
      } else {
        setUploadError('所选资料均未成功上传。')
      }
    } catch (cause) { setUploadError(cause instanceof Error ? cause.message : '资料上传失败') }
  }

  async function handleUploadSourceImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !notebookId) return
    setAssetUploadError(undefined)
    try {
      const result = await api.uploadNotebookAsset(notebookId, file)
      if (result.upload_batch_id) setUploadBatchId(result.upload_batch_id)
      await refreshAssetResources()
      setResourcesOpen(true)
      setNotice(result.processing_job?.status === 'pending'
        ? '原始图片已保存，OCR 任务已排队。'
        : `原始图片已保存${result.asset.state === 'ready' ? '，等待解析' : ''}。`)
    } catch (cause) {
      setAssetUploadError(cause instanceof Error ? cause.message : '图片资料上传失败')
    }
  }

  async function insertSourceAsset(asset: AssetResource) {
    const editor = editorRef.current?.editor
    if (!editor || !notebookId || asset.media_type !== 'image') return
    try {
      const inline = await api.useAssetInline(notebookId, asset.id)
      editor.chain().focus().insertImage({
        src: inline.content_url, assetId: inline.id, alt: asset.original_name,
      }).run()
      setNotice('图片已插入正文；保存后会纳入笔记历史版本。')
    } catch (cause) {
      setAssetUploadError(cause instanceof Error ? cause.message : '插入图片失败')
    }
  }

  async function uploadImage(file: File): Promise<{ src: string; attachmentId: string } | null> {
    if (!courseId || !notebookId) return null
    setImageError(undefined)
    try {
      const attachment = await api.uploadNotebookAttachment(courseId, notebookId, file)
      return { src: attachment.url, attachmentId: attachment.id }
    } catch (cause) {
      setImageError(cause instanceof Error ? cause.message : '图片上传失败')
      return null
    }
  }

  function restoreDraft() {
    if (!draftFound) return
    const restored = normalizeDocument(draftFound.content)
    editorRef.current?.replaceContent(restored)
    setContent(restored)
    setEditVersion((value) => value + 1)
    save.markEdited(restored)
    setDraftFound(null)
    setNotice('已恢复本地草稿，保存成功后会清除草稿副本。')
  }

  async function discardDraft() {
    setDraftFound(null)
    if (courseId && notebookId) await clearDraft(courseId, notebookId)
  }

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(docToMarkdown(content))
      setNotice('本地草稿已复制为 Markdown。')
    } catch {
      setNotice('复制失败，请手动选择正文复制。')
    }
  }

  async function showServerVersion() {
    const latest = await save.fetchServer()
    if (latest) setConflictPreview(latest)
  }

  function useServerVersion() {
    if (!conflictPreview) return
    const normalized = normalizeDocument(conflictPreview.content)
    editorRef.current?.replaceContent(normalized)
    setContent(normalized)
    setEditVersion((value) => value + 1)
    save.applyServer({ ...conflictPreview, content: normalized })
    save.setConflictOpen(false)
    setConflictPreview(null)
    setNotice('已切换到服务器版本。')
  }

  function exportMarkdown() {
    const blob = new Blob([docToMarkdown(content)], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title.trim() || '笔记'}.md`
    anchor.click()
    URL.revokeObjectURL(url)
    setNotice('已导出 Markdown。')
  }

  function exportPdf() {
    const html = editorRef.current?.editor?.getHTML()
    if (!html) return
    const win = window.open('', '_blank')
    if (!win) { setNotice('浏览器阻止了打印窗口，请允许弹窗后重试。'); return }
    const styles = Array.from(document.querySelectorAll('link[rel="stylesheet"], style')).map((node) => node.outerHTML).join('')
    win.document.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8" /><title>${escapeHtml(title)}</title>${styles}<style>
      body{margin:0;background:#fff;color:#24322a;font-family:var(--nb-sans,"Noto Sans SC",sans-serif);}
      article{max-width:760px;margin:0 auto;padding:48px 24px;}
      .ProseMirror{outline:none;}
      h1,h2,h3{break-after:avoid;}
      table{border-collapse:collapse;width:100%;}td,th{border:1px solid #dbe4dc;padding:6px 8px;}
      img{max-width:100%;}
      blockquote{border-left:3px solid #b9d0bc;margin:12px 0;padding-left:14px;color:#4c6352;}
      pre{background:#f4f7f4;padding:12px;border-radius:6px;overflow:auto;}
      @media print{article{padding:0;} .nb-drag-handle,.nb-selection-menu{display:none!important;}}
    </style></head><body><article class="ProseMirror">${html}</article></body></html>`)
    win.document.close()
    win.setTimeout(() => { win.focus(); win.print() }, 450)
  }

  function openAssistant(action?: AIAction) {
    window.dispatchEvent(new CustomEvent('notebuddy:open-assistant', {
      detail: { courseId, notebookId, action, selection, revision: save.revision, title },
    }))
  }

  if (!courseId || !notebookId) return <section className="route-state-card" role="alert">笔记地址无效。</section>
  if (loadError) return <section className="route-state-card" role="alert"><h1>无法打开笔记</h1><p>{loadError}</p><Link className="primary-button link-button" to="/courses">返回课程</Link></section>

  const titleDirty = title !== (outline?.title ?? '')
  const displaySaveState = save.state === 'conflict' ? 'conflict'
    : save.state === 'error' || titleError ? 'error'
      : save.state === 'saving' || titleSaving ? 'saving'
        : save.state === 'unsaved' || titleDirty ? 'unsaved' : 'saved'
  const saveLabel = displaySaveState === 'conflict' ? '有冲突'
    : displaySaveState === 'error' ? titleError ? '名称保存失败' : '保存失败'
      : displaySaveState === 'saving' ? titleSaving ? '名称保存中…' : '保存中…'
        : displaySaveState === 'unsaved' ? titleDirty ? '名称待保存' : '待保存'
          : `已保存${save.lastSavedAt ? ` ${clock(save.lastSavedAt)}` : ''}`

  return <div className="notebook-document-page">
    <header className="notebook-document-topbar">
      <Link className="notebook-document-back" to="/courses" aria-label="返回课程">← <span>课程</span></Link>
      <span className="notebook-document-top-separator" aria-hidden="true" />
      <span className="notebook-document-top-course" title={course?.name}>{course?.name ?? '课程'}</span>
      <span className="notebook-document-top-chevron" aria-hidden="true">›</span>
      <strong className="notebook-document-top-title" title={outline?.title}>{outline?.title ?? '正在读取笔记…'}</strong>

      <div className="notebook-document-top-actions">
        <span className={`notebook-document-save-status notebook-document-save-${displaySaveState}`} role="status" aria-live="polite">
          <span aria-hidden="true" />{saveLabel}
        </span>
        <div className="notebook-document-history-actions" role="group" aria-label="撤销与重做">
          <button type="button" onClick={() => editorRef.current?.undo()} title="撤销（Ctrl+Z）" aria-label="撤销">↶</button>
          <button type="button" onClick={() => editorRef.current?.redo()} title="重做（Ctrl+Shift+Z）" aria-label="重做">↷</button>
        </div>
        <button className="notebook-document-ai-button" type="button" onClick={() => openAssistant()} aria-label="打开 AI 助手">
          <span aria-hidden="true">✦</span> AI 助手
        </button>
        <details className="notebook-document-more">
          <summary aria-label="更多操作">更多</summary>
          <div>
            <button type="button" onClick={() => void save.saveNow()}>立即保存</button>
            <button type="button" onClick={() => setHistoryOpen(true)}>历史版本</button>
            <button type="button" onClick={exportMarkdown}>导出 Markdown</button>
            <button type="button" onClick={exportPdf}>导出 PDF</button>
            <button type="button" onClick={() => void navigator.clipboard.writeText(window.location.href).then(() => setNotice('链接已复制。'))}>复制链接</button>
            <button type="button" onClick={() => { setResourcesOpen(true); document.querySelector('.notebook-document-resource-list')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }}>查看本篇资料</button>
          </div>
        </details>
      </div>
    </header>

    {notice && <div className="notebook-document-notice" role="status">{notice}<button type="button" onClick={() => setNotice(undefined)} aria-label="关闭提示">×</button></div>}
    {save.error && <div className="notebook-document-banner is-error" role="alert">
      <span>{save.error}</span>
      {save.state === 'conflict'
        ? <div><button type="button" onClick={() => save.setConflictOpen(true)}>处理冲突</button><button type="button" onClick={() => void showServerVersion()}>查看服务器版本</button><button type="button" onClick={() => void copyDraft()}>复制本地草稿</button></div>
        : <button type="button" onClick={() => save.retry()}>重试保存</button>}
    </div>}
    {draftFound && <div className="notebook-document-banner" role="status">
      <span>发现 {clock(draftFound.updatedAt)} 的本地草稿，与服务器版本不同。</span>
      <div><button type="button" onClick={restoreDraft}>恢复草稿</button><button type="button" onClick={() => void discardDraft()}>忽略</button></div>
    </div>}
    {documentWarning && <div className="notebook-document-banner" role="alert">{documentWarning}</div>}
    {imageError && <div className="notebook-document-banner is-error" role="alert">{imageError}<button type="button" onClick={() => setImageError(undefined)}>关闭</button></div>}

    <div className="notebook-document-workspace">
      <aside className="notebook-document-sidebar" aria-label="资料与目录">
        <div className="notebook-document-sidebar-heading">资料与目录</div>
        <input ref={fileInput} className="notebook-document-file-input" type="file" accept=".pptx,.pdf,.docx" multiple onChange={(event) => void handleUploadMaterial(event)} aria-label="选择课程资料" />
        <input ref={sourceImageInput} className="notebook-document-file-input" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg" onChange={(event) => void handleUploadSourceImage(event)} aria-label="选择原始图片资料" />
        <button className="notebook-document-upload" type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
          <span aria-hidden="true">＋</span>{busy ? '上传中…' : '上传资料'}
        </button>
        <button className="notebook-document-upload is-secondary" type="button" onClick={() => sourceImageInput.current?.click()}>
          <span aria-hidden="true">▧</span>添加 PNG/JPG 图片资料
        </button>
        <label className="notebook-document-duplicate-option">
          <input type="checkbox" checked={allowDuplicateUploads} onChange={(event) => setAllowDuplicateUploads(event.target.checked)} />
          相同文件也作为新资料导入
        </label>
        {uploadError && <p className="notebook-document-sidebar-error" role="alert">{uploadError}</p>}
        {assetUploadError && <p className="notebook-document-sidebar-error" role="alert">{assetUploadError}</p>}
        {generationError && <p className="notebook-document-sidebar-error" role="alert">{generationError}</p>}
        {uploadBatch && <div className="notebook-document-sidebar-empty" role="status">
          <strong>{uploadBatch.status === 'open' ? '等待本批上传完成…' : uploadBatch.status === 'parsing' || uploadBatch.status === 'waiting_parse' ? '资料正在后台解析…' : uploadBatch.status === 'generating' ? 'AI 正在追加正式正文…' : uploadBatch.status === 'partial_failure' ? '部分资料处理失败，可检查失败项并重试。' : '本批资料已处理完成。'}</strong>
          {uploadBatch.inputs.filter((item) => item.error_message).map((item) => {
            const material = bookMaterials.find((row) => row.asset_id === item.asset_id)
            return <div key={item.asset_id}><small>{item.asset_id.slice(0, 8)}：{item.error_message}</small>
              {item.status === 'parse_failed' && material && <button type="button" onClick={() => void api.retryMaterial(material.id).catch((cause: unknown) => setUploadError(cause instanceof Error ? cause.message : '解析重试失败'))}>重试解析</button>}
            </div>
          })}
        </div>}
        {generationJob && ['pending', 'processing', 'cancel_requested'].includes(generationJob.status) && <p className="notebook-document-sidebar-empty" role="status">{generationJob.status === 'pending' ? '等待 AI 补充正文…' : generationJob.status === 'cancel_requested' ? '正在取消…' : 'AI 正在补充正文…'}</p>}
        {generationJob?.status === 'failed' && <button className="notebook-document-import" type="button" disabled={generationBusy} onClick={() => {
          setGenerationBusy(true)
          void api.retryNotebookGenerationJob(notebookId!, generationJob.id).then(setGenerationJob).catch((cause: unknown) => setGenerationError(cause instanceof Error ? cause.message : '重试失败')).finally(() => setGenerationBusy(false))
        }}>重试 AI 整理</button>}
        {generationJob?.status === 'completed' && <p className="notebook-document-sidebar-empty" role="status">AI 补充内容已写入正式正文</p>}
        <section className="notebook-document-sidebar-section">
          <div className="notebook-document-section-toggle is-static">本篇资源 <small>{assetResources.length}</small></div>
          <div className="notebook-document-resource-list">
            {assetResources.length ? assetResources.map((asset) => <div className="notebook-document-resource-item" key={asset.id}>
              <span title={asset.original_name}>{asset.original_name}</span>
              <small>{asset.state === 'ready' ? asset.role === 'source_material' ? '原始资料' : '正文资源' : asset.state}</small>
              {asset.role === 'source_material' && <button type="button" disabled={asset.state !== 'ready'}
                onClick={() => { const next = new URLSearchParams(searchParams); next.set('asset', asset.id); next.set('page', '1'); setSearchParams(next) }}>查看来源</button>}
              {asset.role === 'source_material' && <details className="notebook-document-material-actions"><summary aria-label={`管理${asset.original_name}`}>更多</summary>
                <button type="button" disabled={Boolean(materialBusyId)} onClick={() => setAssetRemoval(asset)}>从本篇移除</button>
              </details>}
              {asset.media_type === 'image' && asset.state === 'ready' && <button type="button" onClick={() => void insertSourceAsset(asset)}>插入正文</button>}
              {asset.media_type === 'image' && asset.role === 'source_material' && assetJobs[asset.id] && <small className="notebook-document-resource-status">OCR：{assetJobs[asset.id].status === 'completed' ? '完成' : assetJobs[asset.id].status === 'completed_with_warnings' ? '有告警' : assetJobs[asset.id].status === 'failed' ? `失败 · ${assetJobs[asset.id].error_message ?? ''}` : assetJobs[asset.id].status === 'processing' ? '处理中' : '排队中'}</small>}
              {asset.media_type === 'image' && asset.role === 'source_material' && assetJobs[asset.id]?.status === 'failed' && <button type="button" onClick={() => void api.retryAssetParse(asset.id).then((job) => setAssetJobs((current) => ({ ...current, [asset.id]: job }))).catch((cause: unknown) => setAssetUploadError(cause instanceof Error ? cause.message : '重试图片解析失败'))}>重试 OCR</button>}
            </div>) : <p className="notebook-document-sidebar-empty">暂时没有已登记的统一资源</p>}
            {detachedAssetResources.length > 0 && <details className="notebook-document-deleted-materials">
              <summary>可恢复资源 · {detachedAssetResources.length}</summary>
              {detachedAssetResources.map((asset) => <div key={asset.id}>
                <span>{asset.original_name}</span>
                <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void restoreNotebookAsset(asset)}>
                  {materialBusyId === asset.id ? '恢复中…' : '恢复'}
                </button>
              </div>)}
            </details>}
          </div>
        </section>
        <section className="notebook-document-sidebar-section">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={resourcesOpen} onClick={() => setResourcesOpen((value) => !value)}>
            <span className={resourcesOpen ? 'is-open' : ''} aria-hidden="true">⌄</span>课程资料 <small>{bookMaterials.length}</small>
          </button>
          {resourcesOpen && <div className="notebook-document-section-body">
            {materialActionError && <p className="notebook-document-sidebar-error" role="alert">{materialActionError}</p>}
            {bookMaterials.length ? bookMaterials.map((material) => <div className="notebook-document-material-row" key={material.id}>
              <Link className="notebook-document-material"
                to={`/courses/${courseId}/notebooks/${notebookId}${material.asset_id ? `?asset=${encodeURIComponent(material.asset_id)}` : ''}`} title={material.original_filename}>
                <span className="notebook-document-file-icon" aria-hidden="true">{material.original_filename.toLowerCase().endsWith('.pdf') ? 'PDF' : material.original_filename.toLowerCase().endsWith('.pptx') ? 'PPT' : 'DOC'}</span>
                <span><strong>{material.original_filename}</strong><small>{material.status === 'completed' ? `已整理 · ${material.page_count} 页` : material.status === 'failed' ? `处理失败${material.document_warning ? ` · ${material.document_warning}` : ''}` : '正在整理'}</small></span>
              </Link>
              <details className="notebook-document-material-actions"><summary aria-label={`管理${material.original_filename}`}>更多</summary>
                <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void prepareMaterialRemoval(material)}>移除资料</button>
                {material.status === 'failed'
                  ? <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void runMaterialOperation(material.id, 'retry')}>重试解析</button>
                  : <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void runMaterialOperation(material.id, 'reparse')}>重新解析</button>}
              </details>
            </div>) : <p className="notebook-document-sidebar-empty">尚未上传资料</p>}
            {deletedBookMaterials.length > 0 && <details className="notebook-document-deleted-materials">
              <summary>可恢复资料 · {deletedBookMaterials.length}</summary>
              {deletedBookMaterials.map((material) => <div key={material.id}>
                <span>{material.original_filename}</span><button type="button" disabled={Boolean(materialBusyId)}
                  onClick={() => void restoreBookMaterial(material.id)}>{materialBusyId === material.id ? '恢复中…' : '恢复'}</button>
              </div>)}
            </details>}
          </div>}
        </section>
        <section className="notebook-document-sidebar-section notebook-document-sidebar-directory">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={directoryOpen} onClick={() => setDirectoryOpen((value) => !value)}>
            <span className={directoryOpen ? 'is-open' : ''} aria-hidden="true">⌄</span>笔记目录 <small>{headings.length ? `${headings.length} 个标题` : '随标题更新'}</small>
          </button>
          {directoryOpen && <nav className="notebook-document-section-body" aria-label="笔记目录">
            {headings.length ? headings.map((heading) => <button
              className={`notebook-document-outline-item notebook-document-outline-h${heading.level}${activeBlockId === heading.id ? ' is-active' : ''}`}
              key={heading.id}
              type="button"
              onClick={() => {
                editorRef.current?.focusBlock(heading.id)
                setActiveBlockId(heading.id)
              }}
            >{heading.text}</button>) : <p className="notebook-document-sidebar-empty">正文标题会显示在这里</p>}
          </nav>}
        </section>
      </aside>

      <main className="notebook-document-canvas" aria-label="笔记正文">
        <div className="notebook-document-breadcrumb"><span>课程笔记</span><span aria-hidden="true">›</span><span>{course?.name ?? '课程'}</span><span aria-hidden="true">›</span><span>{outline?.title ?? '笔记'}</span></div>
        {!loaded ? <div className="notebook-document-loading" role="status">正在读取笔记正文…</div> : <article className="notebook-document-paper">
          <input className="notebook-document-title" value={title} onChange={(event) => { setTitle(event.target.value); setTitleError(undefined) }} onBlur={() => void renameTitle()} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} aria-label="笔记名称" maxLength={200} />
          <div className="notebook-document-meta">
            <span>{course?.name ?? '课程'} · {bookMaterials.length} 份资料 · 约 {wordCount.toLocaleString('zh-CN')} 字</span>
            {save.lastSavedAt && <span>最后编辑 {clock(save.lastSavedAt)}</span>}
          </div>
          {titleError && <p className="notebook-document-error" role="alert">{titleError}</p>}
          <NotebookEditor
            ref={editorRef}
            initialContent={content}
            onChange={handleChange}
            onSelectionChange={setSelection}
            onRequestAI={(action) => openAssistant(action)}
            onUploadImage={uploadImage}
            onSaveShortcut={() => void save.saveNow()}
            onReady={(editor) => {
              editorReadyRef.current = true
              save.reset(editor.getJSON() as DocNode, save.revision, save.lastSavedAt)
            }}
          />
        </article>}
      </main>
      {linkedAssetId && assetResourcesLoaded && notebookId && (() => {
        const asset = assetResources.find((item) => item.id === linkedAssetId && item.role === 'source_material')
        const materialId = bookMaterials.find((item) => item.asset_id === asset?.id)?.id
        return asset ? <DocumentSourcePreview assetId={asset.id} notebookId={notebookId} materialId={materialId}
          initialPage={Number.isInteger(linkedAssetPage) && linkedAssetPage > 0 ? linkedAssetPage : 1}
          fileName={asset.original_name} mimeType={asset.mime_type} originalUrl={asset.content_url} onClose={closeAssetPreview} />
          : <div className="document-source-backdrop" role="presentation"><section className="document-source-dialog" role="alertdialog" aria-modal="true" aria-label="资料不可用">
            <p>这份资料不属于当前 Notebook 或已不可用。</p><button type="button" onClick={closeAssetPreview}>关闭</button>
          </section></div>
      })()}
      {materialRemoval && <ConfirmDialog
        eyebrow="Notebook 资料管理"
        title={`移除“${bookMaterials.find((item) => item.id === materialRemoval.id)?.original_filename ?? '这份资料'}”？`}
        description="资料会从当前 Notebook 隐藏，并进入可恢复资料列表。受保护的用户笔记不会被删除。"
        confirmLabel="确认移除资料" cancelLabel="保留资料" tone="danger"
        pending={Boolean(materialBusyId)} pendingLabel="正在移除…" error={materialActionError}
        onConfirm={() => void confirmMaterialRemoval()} onCancel={() => setMaterialRemoval(undefined)}>
        <div className="deletion-impact" aria-label="移除影响范围">
          <span><strong>{materialRemoval.impact.pages}</strong><small>个页面</small></span>
          <span><strong>{materialRemoval.impact.source_refs}</strong><small>条来源</small></span>
          <span><strong>{materialRemoval.impact.user_notes_protected}</strong><small>条受保护笔记</small></span>
        </div>
      </ConfirmDialog>}
      {assetRemoval && <ConfirmDialog
        eyebrow="Notebook 资源管理"
        title={`从本篇移除“${assetRemoval.original_name}”？`}
        description="此操作解除资源与当前 Notebook 的关联。源文件不会立即物理删除；正文附件或历史版本仍引用时会继续保留。"
        confirmLabel="确认移除" cancelLabel="保留资源" tone="danger"
        pending={Boolean(materialBusyId)} pendingLabel="正在移除…" error={materialActionError}
        onConfirm={() => void removeNotebookAsset()} onCancel={() => setAssetRemoval(undefined)} />}
    </div>

    {save.conflictOpen && <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="保存冲突">
      <div className="nb-modal">
        <h2>这篇笔记已在别处更新</h2>
        <p>你的本地修改仍然保留。请选择要保留的版本，系统不会自动覆盖任何一方。</p>
        <ul className="notebook-document-conflict-list">
          <li>服务器版本：revision {save.revision}</li>
          <li>本地草稿：{wordCount} 字</li>
        </ul>
        <div className="nb-modal-actions is-stacked">
          <button type="button" onClick={() => void showServerVersion()}>查看服务器版本</button>
          <button type="button" onClick={() => void copyDraft()}>复制本地草稿</button>
          <button type="button" onClick={() => save.keepLocalDraft()}>保留本地草稿，暂停自动保存</button>
          <button type="button" className="is-danger" onClick={() => void save.overwriteServer()}>用本地版本覆盖服务器</button>
          <button type="button" className="primary-button" onClick={() => save.setConflictOpen(false)}>继续编辑</button>
        </div>
      </div>
    </div>}

    {conflictPreview && <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="服务器版本预览">
      <div className="nb-modal is-wide">
        <h2>服务器上的最新版本</h2>
        <pre className="notebook-document-conflict-preview">{docToMarkdown(conflictPreview.content).slice(0, 12_000)}</pre>
        <div className="nb-modal-actions">
          <button type="button" onClick={() => setConflictPreview(null)}>返回</button>
          <button type="button" className="primary-button" onClick={useServerVersion}>用服务器版本替换编辑器</button>
        </div>
      </div>
    </div>}

    {historyOpen && <NotebookHistoryPanel
      courseId={courseId}
      notebookId={notebookId}
      beforeRestore={async () => {
        if (save.isDirty() && !await save.saveNow()) return null
        return save.isDirty() ? null : save.getRevision()
      }}
      onClose={() => setHistoryOpen(false)}
      onRestored={(document, revision, updatedAt) => {
        const normalized = normalizeDocument(document)
        editorRef.current?.replaceContent(normalized)
        setContent(normalized)
        setEditVersion((value) => value + 1)
        save.reset(normalized, revision, updatedAt)
        setHistoryOpen(false)
        setNotice('已恢复到选中的历史版本，并生成新的修订。')
      }}
    />}
  </div>
}

function NotebookHistoryPanel({ courseId, notebookId, beforeRestore, onClose, onRestored }: {
  courseId: string
  notebookId: string
  beforeRestore: () => Promise<number | null>
  onClose: () => void
  onRestored: (content: DocNode, revision: number, updatedAt: string) => void
}) {
  const [items, setItems] = useState<Array<{ revision: number; origin: string; created_at: string }>>([])
  const [preview, setPreview] = useState<DocNode | null>(null)
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null)
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    void api.listNotebookRevisions(courseId, notebookId).then((rows) => {
      if (active) setItems(rows)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '历史版本读取失败')
    })
    return () => { active = false }
  }, [courseId, notebookId])

  async function loadPreview(revision: number) {
    setBusy(true)
    setSelectedRevision(revision)
    try {
      const snapshot = await api.getNotebookRevision(courseId, notebookId, revision)
      setPreview(snapshot.content)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '版本内容读取失败')
    } finally { setBusy(false) }
  }

  async function restore() {
    if (selectedRevision === null) return
    if (!window.confirm(`恢复 revision ${selectedRevision}？已保存的当前版本会保留在历史中，恢复操作会生成新修订。`)) return
    setBusy(true)
    try {
      const expectedRevision = await beforeRestore()
      if (expectedRevision === null) {
        setError('当前正文尚未保存，请先完成保存或处理冲突，再恢复历史版本。')
        return
      }
      const restored = await api.restoreNotebookRevision(courseId, notebookId, selectedRevision, expectedRevision)
      onRestored(restored.content, restored.revision, restored.updated_at)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '恢复失败')
    } finally { setBusy(false) }
  }

  return <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="历史版本">
    <div className="nb-modal is-wide">
      <div className="nb-modal-head"><h2>历史版本</h2><button type="button" onClick={onClose} aria-label="关闭">×</button></div>
      {error && <p className="notebook-document-error" role="alert">{error}</p>}
      <div className="notebook-document-history">
        <div className="notebook-document-history-list">
          {items.length ? items.map((item) => <button key={item.revision} type="button" className={selectedRevision === item.revision ? 'is-active' : ''} onClick={() => void loadPreview(item.revision)}>
            <strong>revision {item.revision}</strong>
            <span>{serverDate(item.created_at).toLocaleString('zh-CN')}</span>
            <small>{item.origin === 'restore' ? '恢复生成' : item.origin === 'autosave' ? '自动保存' : item.origin}</small>
          </button>) : <p className="notebook-document-sidebar-empty">还没有历史快照。</p>}
        </div>
        <div className="notebook-document-history-preview">
          {preview ? <pre>{docToMarkdown(preview).slice(0, 20_000)}</pre> : <p>选择左侧版本查看内容。</p>}
        </div>
      </div>
      <div className="nb-modal-actions">
        <button type="button" onClick={onClose}>关闭</button>
        <button type="button" className="primary-button" disabled={selectedRevision === null || busy} onClick={() => void restore()}>恢复到此版本（生成新修订）</button>
      </div>
    </div>
  </div>
}
