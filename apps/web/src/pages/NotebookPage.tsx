import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useWorkspace } from '../components/AppLayout'
import type { AssetResource, Material } from '../types'
import { ProcessingRouteControl, useProcessingRoute } from '../features/notebook/useProcessingRoute'
import {
  NotebookEditor, type AIAction, type NotebookEditorHandle, type SelectionAnchor,
} from '../features/notebook-editor/NotebookEditor'
import {
  countText, docToMarkdown, excerptAroundSelection, extractOutline, normalizeDocument, type DocNode,
} from '../features/notebook-editor/document'
import { useDocumentReadingPosition } from '../features/notebook-editor/useDocumentReadingPosition'
import { useRegisterNotebookBridge, type NotebookBridgeValue } from '../features/notebook-editor/NotebookBridge'
import { DocumentSourcePreview } from '../features/notebook-editor/DocumentSourcePreview'
import { historyOriginLabel, useHistoryDialog } from '../features/notebook-editor/historyDialog'
import { useNotebookIdentity } from '../features/notebook-workspace/hooks/useNotebookIdentity'
import { useNotebookDocument } from '../features/notebook-workspace/hooks/useNotebookDocument'
import { useNotebookGeneration } from '../features/notebook-workspace/hooks/useNotebookGeneration'
import { useNotebookResources } from '../features/notebook-workspace/hooks/useNotebookResources'
import { SourceUploadPanel } from '../features/notebook-workspace/SourceUploadPanel'
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

/**
 * Notebook Workspace 的组合层。
 *
 * 正文、资料资源、上传/生成三条业务线分别由 `useNotebookDocument`、
 * `useNotebookResources`、`useNotebookGeneration` 承载；本文件只负责路由身份、
 * 深链与选区、以及把三者的结果拼成页面。它不再直接编排模型调用或资料事务。
 */
function NotebookPageBody() {
  const { isUnbound, courseId, notebookId, api: notebookApi } = useNotebookIdentity()
  const [searchParams, setSearchParams] = useSearchParams()
  const linkedSectionId = searchParams.get('section')
  const linkedChapterId = searchParams.get('chapter')
  const linkedAssetId = searchParams.get('asset')
  const uploadRequested = searchParams.get('upload') === '1'
  const linkedAssetPage = Number(searchParams.get('page') || 1)
  const { course, materials, busy, documentDirty, uploadMaterial, refreshCurrentMaterials, setDocumentDirty } = useWorkspace()

  /* 仅属于页面外壳的 UI 状态（面板开合、提示条、弹窗） */
  const [notice, setNotice] = useState<string>()
  const [resourcesOpen, setResourcesOpen] = useState(true)
  const [directoryOpen, setDirectoryOpen] = useState(true)
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false)
  const [activeBlockId, setActiveBlockId] = useState<string>()
  const [selection, setSelection] = useState<SelectionAnchor | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceImageInput = useRef<HTMLInputElement>(null)
  const editorRef = useRef<NotebookEditorHandle>(null)
  const lastDeepLinkRef = useRef<string | undefined>(undefined)
  const { route: processingRoute, setRoute: setProcessingRoute } = useProcessingRoute()

  const doc = useNotebookDocument({
    notebookId, courseId, notebookApi, editorRef, onNotice: setNotice,
  })
  const resources = useNotebookResources({
    notebookId, courseId, isUnbound, loaded: doc.loaded, materials,
    refreshCurrentMaterials, notebookApi, editorRef, onNotice: setNotice,
    processingRoute,
  })
  const generation = useNotebookGeneration({
    notebookId, courseId, isUnbound, loaded: doc.loaded, bookMaterials: resources.bookMaterials,
    refreshCurrentMaterials, uploadMaterial: uploadMaterial as never,
    reloadOutline: doc.reloadOutline, onRefresh: doc.refreshNotebookAfterUpload,
    refreshIfNewer: doc.refreshIfNewer, onNotice: setNotice,
    processingRoute,
  })

  const {
    outline, title, setTitle, content, setContent, loaded, editorReady, setEditorReady,
    loadError, documentWarning, titleError, setTitleError, titleSaving, lastTitleSavedAt,
    draftFound, conflictPreview, setConflictPreview, editVersion, setEditVersion,
    save, dirty, editorReadyRef, handleChange, insertAI, adoptDocument, renameTitle,
    refreshNotebookAfterUpload, restoreDraft, discardDraft, showServerVersion, useServerVersion,
  } = doc
  const {
    bookMaterials, sourceImages, fileBudgets, assetResources, assetResourcesLoaded,
    materialRemoval, setMaterialRemoval, materialActionError, setMaterialActionError,
    materialBusyId, assetUploadError, setAssetUploadError, imageError, setImageError,
    assetRemoval, setAssetRemoval, deletedBookMaterials, detachedAssetResources,
    prepareMaterialRemoval, confirmMaterialRemoval, restoreBookMaterial, runMaterialOperation,
    restoreNotebookAsset, insertSourceAsset, uploadImage,
  } = resources
  const {
    uploadBatch, setUploadBatch, uploadBatchId, setUploadBatchId, generationJob, setGenerationJob,
    generationBusy, generationError, setGenerationError, uploadProgress, setUploadProgress,
    uploadError, allowDuplicateUploads, setAllowDuplicateUploads,
    aiReadingProgress, generationStatusCoveredByToast, handleUploadMaterial: runUploadMaterial,
    retryUploadProgress: runRetryUploadProgress, retryGenerationJob,
  } = generation

  const handleUploadMaterial = (event: ChangeEvent<HTMLInputElement>) => {
    void runUploadMaterial(event).then(() => setResourcesOpen(true))
  }

  const retryUploadProgress = async () => {
    const outcome = await runRetryUploadProgress()
    if (outcome === 'pick-file') fileInput.current?.click()
  }

  async function handleUploadSourceImage(event: ChangeEvent<HTMLInputElement>) {
    const result = await resources.handleUploadSourceImage(event)
    if (!result) return
    if (result.upload_batch_id) setUploadBatchId(result.upload_batch_id)
    setResourcesOpen(true)
  }

  async function removeNotebookAsset() {
    await resources.removeNotebookAsset(() => { if (linkedAssetId) closeAssetPreview() })
  }

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(docToMarkdown(content))
      setNotice('本地草稿已复制为 Markdown。')
    } catch {
      setNotice('复制失败，请手动选择正文复制。')
    }
  }

  const headings = useMemo(() => extractOutline(content), [content])

  useDocumentReadingPosition({
    courseId, notebookId, editorRef, ready: loaded && editorReady,
    explicitLink: Boolean(linkedSectionId || linkedChapterId),
    onRestore: setActiveBlockId,
  })

  /* 未保存状态同步给全局布局：离开页面/切换课程时要能提醒 */
  useEffect(() => {
    setDocumentDirty(Boolean(loaded && dirty))
  }, [dirty, loaded, setDocumentDirty])
  useEffect(() => () => setDocumentDirty(false), [setDocumentDirty])

  /* 深链（知识森林/课程页跳转）定位到章节块，同一目标只处理一次 */
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

  /* ?upload=1 由外部入口触发文件选择器；读完参数后清掉，避免刷新重复弹出 */
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

  const bridgeValue = useMemo<NotebookBridgeValue | null>(() => notebookId && loaded ? {
    courseId: isUnbound ? null : courseId,
    notebookId,
    title,
    revision: save.revision,
    editVersion,
    excerpt: excerptAroundSelection(content, selection?.text),
    selection,
    insertAI,
    isDirty: save.isDirty,
    adoptDocument,
  } : null, [adoptDocument, content, courseId, editVersion, insertAI, isUnbound, loaded, notebookId, save.isDirty, save.revision, selection, title])
  useRegisterNotebookBridge(bridgeValue)

  const wordCount = useMemo(() => countText(content), [content])

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
      detail: { courseId: isUnbound ? null : courseId, notebookId, action, selection, revision: save.revision, title },
    }))
  }

  if (!notebookId) return <section className="route-state-card" role="alert">笔记地址无效。</section>
  if (loadError) return <section className="route-state-card" role="alert"><h1>无法打开笔记</h1><p>{loadError}</p><Link className="primary-button link-button" to="/courses">返回课程</Link></section>

  const titleDirty = title !== (outline?.title ?? '')
  const displaySaveState = save.state === 'conflict' ? 'conflict'
    : save.state === 'error' || titleError ? 'error'
      : save.state === 'saving' || titleSaving ? 'saving'
        : save.state === 'unsaved' || titleDirty ? 'unsaved' : 'saved'
  const lastEditedAt = [save.lastSavedAt, lastTitleSavedAt]
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => serverDate(right).getTime() - serverDate(left).getTime())[0]
  const saveLabel = displaySaveState === 'conflict' ? '有冲突'
    : displaySaveState === 'error' ? titleError ? '名称保存失败' : '保存失败'
      : displaySaveState === 'saving' ? titleSaving ? '名称保存中…' : '保存中…'
        : displaySaveState === 'unsaved' ? titleDirty ? '名称待保存' : '待保存'
          : `已保存${lastEditedAt ? ` ${clock(lastEditedAt)}` : ''}`

  return <div className="notebook-document-page">
    <header className="notebook-document-topbar">
      <Link className="notebook-document-back" to="/courses" aria-label="返回课程">← <span>课程</span></Link>
      <span className="notebook-document-top-separator" aria-hidden="true" />
      <span className="notebook-document-top-course" title={isUnbound ? '未分类' : course?.name}>{isUnbound ? '未分类' : course?.name ?? '课程'}</span>
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
        <div className="notebook-document-quick-actions" role="group" aria-label="笔记操作">
          <button type="button" onClick={() => void save.saveNow()}>立即保存</button>
          <button type="button" onClick={() => setHistoryOpen(true)}>历史版本</button>
          <button type="button" onClick={exportMarkdown}>导出 Markdown</button>
          <button type="button" onClick={exportPdf}>导出 PDF</button>
          <button type="button" onClick={() => void navigator.clipboard.writeText(window.location.href).then(() => setNotice('链接已复制。'))}>复制链接</button>
          <button type="button" onClick={() => { setResourcesOpen(true); document.querySelector('.notebook-document-resource-list')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }}>查看本篇资料</button>
        </div>
      </div>
    </header>

    {notice && <div className="notebook-document-notice" role="status">{notice}<button type="button" onClick={() => setNotice(undefined)} aria-label="关闭提示">×</button></div>}
    {uploadBatch?.relation_jobs?.map(item => <div className="notebook-document-notice" role="status" key={item.id}>知识联系：{item.status === 'completed' ? '藤蔓分析完成' : item.status === 'failed' ? item.error_message ?? '分析失败，笔记已保留' : '正在分析藤蔓关系'}{item.status === 'failed' && <button type="button" onClick={() => {
      void api.retryForestJob(item.id).then(() => api.getNotebookUploadBatch(notebookId!, uploadBatch.id)).then(setUploadBatch).catch(cause => setMaterialActionError(String(cause)))
    }}>重试联系分析</button>}</div>)}
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

    <div className={`notebook-document-workspace${leftPanelCollapsed ? ' is-left-panel-collapsed' : ''}`}>
      <aside className="notebook-document-sidebar" aria-label="资料与目录">
        <div className="notebook-document-sidebar-heading"><span>资料与目录</span><button type="button" aria-label={leftPanelCollapsed ? '展开资料与目录' : '收起资料与目录'} aria-expanded={!leftPanelCollapsed} onClick={() => setLeftPanelCollapsed((value) => !value)}>{leftPanelCollapsed ? '»' : '«'}</button></div>
        {isUnbound ? <SourceUploadPanel notebookId={notebookId} onDocumentUpdated={() => void refreshNotebookAfterUpload('unbound-upload')} /> : <>
        <input ref={fileInput} className="notebook-document-file-input" type="file" accept=".pptx,.pdf,.docx" multiple onChange={(event) => void handleUploadMaterial(event)} aria-label="选择课程资料" />
        <ProcessingRouteControl value={processingRoute} onChange={setProcessingRoute} disabled={busy} />
        {Boolean(aiReadingProgress?.count) && <p className="notebook-document-sidebar-empty" role="status">AI 读取：{aiReadingProgress!.total > 0 ? `${aiReadingProgress!.done} / ${aiReadingProgress!.total} 页` : '准备页面中'}</p>}
        <input ref={sourceImageInput} className="notebook-document-file-input" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg" onChange={(event) => void handleUploadSourceImage(event)} aria-label="选择原始图片资料" />
        <button className="notebook-document-upload" type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
          <span aria-hidden="true">＋</span>{uploadProgress?.phase === 'uploading' ? '上传中…' : '上传资料'}
        </button>
        <label className="notebook-document-duplicate-option">
          <input type="checkbox" checked={allowDuplicateUploads}
            onChange={(event) => setAllowDuplicateUploads(event.target.checked)} />
          相同文件也作为新资料导入
        </label>
        </>}
        {uploadError && <p className="notebook-document-sidebar-error" role="alert">{uploadError}</p>}
        {assetUploadError && <p className="notebook-document-sidebar-error" role="alert">{assetUploadError}</p>}
        {generationError && <p className="notebook-document-sidebar-error" role="alert">{generationError}</p>}
        {!generationStatusCoveredByToast && generationJob && ['pending', 'processing', 'cancel_requested'].includes(generationJob.status) && <p className="notebook-document-sidebar-empty" role="status">{generationJob.status === 'pending' ? '等待 AI 补充正文…' : generationJob.status === 'cancel_requested' ? '正在取消…' : 'AI 正在补充正文…'}</p>}
        {!generationStatusCoveredByToast && generationJob?.status === 'failed' && <button className="notebook-document-import" type="button" disabled={generationBusy} onClick={() => void retryGenerationJob()}>重试 AI 整理</button>}
        {!generationStatusCoveredByToast && generationJob?.status === 'completed' && <p className="notebook-document-sidebar-empty" role="status">AI 补充内容已写入正式正文</p>}
        <section className="notebook-document-sidebar-section notebook-document-materials-section">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={resourcesOpen} onClick={() => setResourcesOpen((value) => !value)}>
            <strong>{isUnbound ? '笔记资料' : '课程资料'}</strong><span className={`notebook-document-section-chevron${resourcesOpen ? ' is-open' : ''}`} aria-hidden="true">›</span>
          </button>
          {resourcesOpen && <div className="notebook-document-section-body">
            {materialActionError && <p className="notebook-document-sidebar-error" role="alert">{materialActionError}</p>}
            {bookMaterials.length ? <ul className="notebook-document-material-list">{bookMaterials.map((material) => <li className="notebook-document-material-row" key={material.id}>
              <Link className="notebook-document-material"
                to={courseId
                  ? `/courses/${courseId}/notebooks/${notebookId}${material.asset_id ? `?asset=${encodeURIComponent(material.asset_id)}` : ''}`
                  : `/notebooks/unbound/${notebookId}${material.asset_id ? `?asset=${encodeURIComponent(material.asset_id)}` : ''}`} title={material.original_filename}>
                <span><strong>{material.original_filename}</strong><small>{material.status === 'completed' ? '已整理' : material.status === 'failed' ? `处理失败${material.document_warning ? ` · ${material.document_warning}` : ''}` : '正在整理'}{material.asset_id && fileBudgets[material.asset_id] ? ` · 文件预算 ¥${(fileBudgets[material.asset_id].remaining_fen / 100).toFixed(2)} 可用${fileBudgets[material.asset_id].status === 'active' ? '' : ` · ${fileBudgets[material.asset_id].status === 'exhausted' ? '已耗尽' : fileBudgets[material.asset_id].status === 'uncertain' ? '费用待核' : fileBudgets[material.asset_id].status === 'overrun' ? '超出上限' : '已关闭'}`}` : ''}</small></span>
              </Link>
              <details className="notebook-document-material-actions"><summary aria-label={`管理${material.original_filename}`}>⋯</summary>
                {material.status === 'failed' && material.asset_id && material.processing_route !== 'llm' && <button type="button" onClick={() => {
                  void api.switchAssetProcessingRoute(material.asset_id!, 'llm').then(() => refreshCurrentMaterials()).catch(cause => setMaterialActionError(String(cause)))
                }}>改用全程 AI</button>}
                {['pending', 'processing'].includes(material.status) && material.asset_id && material.processing_route === 'llm' && <button type="button" onClick={() => {
                  void api.cancelAssetProcessing(material.asset_id!).then(() => refreshCurrentMaterials()).catch(cause => setMaterialActionError(String(cause)))
                }}>取消读取</button>}
                <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void prepareMaterialRemoval(material)}>移除资料</button>
                {material.status === 'failed'
                  ? <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void runMaterialOperation(material.id, 'retry')}>重试解析</button>
                  : <button type="button" disabled={Boolean(materialBusyId)} onClick={() => void runMaterialOperation(material.id, 'reparse')}>重新解析</button>}
              </details>
            </li>)}</ul> : <p className="notebook-document-sidebar-empty">尚未上传资料</p>}
            {sourceImages.length > 0 && <div className="notebook-document-image-resources" aria-label="图片资源">
              <strong>图片资源</strong>
              {sourceImages.map((asset) => <div className="notebook-document-image-resource" key={asset.id}>
                <span title={asset.original_name}>{asset.original_name}{fileBudgets[asset.id] && <small> · 预算可用 ¥{(fileBudgets[asset.id].remaining_fen / 100).toFixed(2)}{fileBudgets[asset.id].status === 'active' ? '' : ` · ${fileBudgets[asset.id].status === 'exhausted' ? '已耗尽' : fileBudgets[asset.id].status === 'uncertain' ? '费用待核' : fileBudgets[asset.id].status === 'overrun' ? '超出上限' : '已关闭'}`}</small>}</span>
                <button type="button" disabled={Boolean(materialBusyId)}
                  onClick={() => void insertSourceAsset(asset)}>插入正文</button>
                <button type="button" disabled={Boolean(materialBusyId)}
                  aria-label={`移除${asset.original_name}`}
                  onClick={() => setAssetRemoval(asset)}>移除</button>
              </div>)}
            </div>}
            {deletedBookMaterials.length > 0 && <details className="notebook-document-deleted-materials">
              <summary>可恢复资料 · {deletedBookMaterials.length}</summary>
              {deletedBookMaterials.map((material) => <div key={material.id}>
                <span>{material.original_filename}</span><button type="button" disabled={Boolean(materialBusyId)}
                  onClick={() => void restoreBookMaterial(material.id)}>{materialBusyId === material.id ? '恢复中…' : '恢复'}</button>
              </div>)}
            </details>}
            {detachedAssetResources.length > 0 && <details className="notebook-document-detached-assets">
              <summary>可恢复资源 · {detachedAssetResources.length}</summary>
              {detachedAssetResources.map((asset) => <div key={asset.id}>
                <span>{asset.original_name}</span>
                <button type="button" disabled={Boolean(materialBusyId)}
                  onClick={() => void restoreNotebookAsset(asset)}>
                  {materialBusyId === asset.id ? '恢复中…' : '恢复'}
                </button>
              </div>)}
            </details>}
          </div>}
        </section>
        <section className="notebook-document-sidebar-section notebook-document-sidebar-directory">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={directoryOpen} onClick={() => setDirectoryOpen((value) => !value)}>
            <strong>笔记目录</strong><small>{headings.length ? `${headings.length} 个标题` : '随标题更新'}</small><span className={`notebook-document-section-chevron${directoryOpen ? ' is-open' : ''}`} aria-hidden="true">›</span>
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
        {uploadProgress && <aside className={`notebook-document-progress-toast is-${uploadProgress.phase}`} role="status" aria-live="polite">
          <span className="notebook-document-progress-indicator" aria-hidden="true">{['complete', 'complete-protected'].includes(uploadProgress.phase) ? '✓' : uploadProgress.phase === 'failed' ? '!' : ''}</span>
          <div className="notebook-document-progress-copy">
            <strong>{uploadProgress.phase === 'uploading' ? '正在上传资料'
              : uploadProgress.phase === 'parsing' ? '解析文件中'
                : uploadProgress.phase === 'generating' ? '正在生成学习笔记'
                  : uploadProgress.phase === 'refreshing' ? '正在载入笔记正文'
                    : uploadProgress.phase === 'complete' ? '学习笔记已更新'
                      : uploadProgress.phase === 'complete-protected' ? '学习笔记已生成，已保留本地修改'
                      : uploadProgress.errorKind === 'parse' ? '资料解析未完成'
                        : uploadProgress.errorKind === 'generation' ? '学习笔记生成失败'
                          : uploadProgress.errorKind === 'refresh' ? '正文载入失败' : '资料上传失败'}</strong>
            <span>{uploadProgress.message ?? (uploadProgress.phase === 'uploading'
              ? `${uploadProgress.fileNames.length} 份资料正在上传。`
              : uploadProgress.phase === 'parsing'
                ? uploadProgress.fileNames.length === 1 ? `${uploadProgress.fileNames[0]} · 解析完成后自动继续。` : '等待资料解析完成，随后自动生成笔记。'
                : uploadProgress.phase === 'generating' ? '解析已完成，正在整理内容并写入 Notebook。'
                  : uploadProgress.phase === 'refreshing' ? '生成已完成，正在读取最新正文。'
                    : uploadProgress.phase === 'complete' ? '正文已载入，提示即将关闭。' : '请重试失败项。')}</span>
            {!['complete', 'complete-protected'].includes(uploadProgress.phase) && <ol className="notebook-document-progress-steps" aria-label="处理步骤">
              <li className={uploadProgress.phase === 'uploading' ? 'is-current' : 'is-complete'}>上传</li>
              <li className={uploadProgress.phase === 'parsing' || (uploadProgress.phase === 'failed' && uploadProgress.errorKind === 'parse') ? 'is-current' : ['generating', 'refreshing', 'complete'].includes(uploadProgress.phase) || (uploadProgress.phase === 'failed' && uploadProgress.errorKind !== 'parse' && uploadProgress.errorKind !== 'upload') ? 'is-complete' : ''}>解析</li>
              <li className={uploadProgress.phase === 'generating' || (uploadProgress.phase === 'failed' && uploadProgress.errorKind === 'generation') ? 'is-current' : ['refreshing', 'complete'].includes(uploadProgress.phase) || (uploadProgress.phase === 'failed' && uploadProgress.errorKind === 'refresh') ? 'is-complete' : ''}>生成笔记</li>
            </ol>}
          </div>
          {uploadProgress.phase === 'failed' && <button className="notebook-document-progress-retry" type="button" disabled={generationBusy} onClick={() => void retryUploadProgress()}>
            {generationBusy ? '重试中…' : uploadProgress.errorKind === 'upload' ? '重新选择文件' : uploadProgress.errorKind === 'refresh' ? '重试载入' : '重试失败项'}
          </button>}
          <button className="notebook-document-progress-close" type="button" aria-label="关闭处理提示；任务会继续" title="关闭提示，任务会继续" onClick={() => setUploadProgress(null)}>×</button>
        </aside>}
        {!loaded ? <div className="notebook-document-loading" role="status">正在读取笔记正文…</div> : <article className="notebook-document-paper">
          <input className="notebook-document-title" value={title} onChange={(event) => { setTitle(event.target.value); setTitleError(undefined) }} onBlur={() => void renameTitle()} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} aria-label="笔记名称" maxLength={200} />
          <div className="notebook-document-meta">
            <span>{isUnbound ? '未分类' : course?.name ?? '课程'} · {bookMaterials.length || assetResources.length} 份资料 · 约 {wordCount.toLocaleString('zh-CN')} 字</span>
            {lastEditedAt && <span title={serverDate(lastEditedAt).toLocaleString('zh-CN')}>最后编辑 {clock(lastEditedAt)}</span>}
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
              setEditorReady(true)
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
      notebookApi={notebookApi}
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

function NotebookHistoryPanel({ notebookApi, notebookId, beforeRestore, onClose, onRestored }: {
  notebookApi: ReturnType<typeof useNotebookIdentity>['api']
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
  const dialogRef = useHistoryDialog(onClose, busy)

  useEffect(() => {
    let active = true
    void notebookApi.listRevisions().then((rows) => {
      if (active) setItems(rows)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '历史版本读取失败')
    })
    return () => { active = false }
  }, [notebookApi, notebookId])

  async function loadPreview(revision: number) {
    if (busy) return
    setBusy(true)
    setSelectedRevision(revision)
    try {
      const snapshot = await notebookApi.getRevision(revision)
      setPreview(snapshot.content)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '版本内容读取失败')
    } finally { setBusy(false) }
  }

  async function restore() {
    if (selectedRevision === null || busy) return
    if (!window.confirm(`恢复 revision ${selectedRevision}？已保存的当前版本会保留在历史中，恢复操作会生成新修订。`)) return
    setBusy(true)
    try {
      const expectedRevision = await beforeRestore()
      if (expectedRevision === null) {
        setError('当前正文尚未保存，请先完成保存或处理冲突，再恢复历史版本。')
        return
      }
      const restored = await notebookApi.restoreRevision(selectedRevision, expectedRevision)
      onRestored(restored.content, restored.revision, restored.updated_at)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '恢复失败')
    } finally { setBusy(false) }
  }

  return <div ref={dialogRef} className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="历史版本" aria-busy={busy} tabIndex={-1}>
    <div className="nb-modal is-wide">
      <div className="nb-modal-head"><h2>历史版本</h2><button type="button" onClick={onClose} disabled={busy} aria-label="关闭">×</button></div>
      {error && <p className="notebook-document-error" role="alert">{error}</p>}
      <div className="notebook-document-history">
        <div className="notebook-document-history-list">
          {items.length ? items.map((item) => <button key={item.revision} type="button" disabled={busy} className={selectedRevision === item.revision ? 'is-active' : ''} onClick={() => void loadPreview(item.revision)}>
            <strong>revision {item.revision}</strong>
            <span>{serverDate(item.created_at).toLocaleString('zh-CN')}</span>
            <small>{historyOriginLabel(item.origin)}</small>
          </button>) : <p className="notebook-document-sidebar-empty">还没有历史快照。</p>}
        </div>
        <div className="notebook-document-history-preview">
          {preview ? <pre>{docToMarkdown(preview).slice(0, 20_000)}</pre> : <p>选择左侧版本查看内容。</p>}
        </div>
      </div>
      <div className="nb-modal-actions">
        <button type="button" onClick={onClose} disabled={busy}>关闭</button>
        <button type="button" className="primary-button" disabled={selectedRevision === null || busy} onClick={() => void restore()}>恢复到此版本（生成新修订）</button>
      </div>
    </div>
  </div>
}
