import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from '../api'
import { EmptyState } from '../components/EmptyState'
import { CoverageGrid } from '../components/CoverageGrid'
import { ProcessingStatus } from '../components/ProcessingStatus'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useWorkspace } from '../components/AppLayout'
import type { Capabilities } from '../api/config'
import type { Coverage, DeletionPreview, PageEvidence, NotebookSummary } from '../types'
import { NotebookRootMenu } from '../features/notebook/NotebookRootMenu'
import type { ForestCourse } from '../features/forest/types'
import { ProcessingRouteControl, useProcessingRoute } from '../features/notebook/useProcessingRoute'

const statusLabels: Record<string, string> = { pending: '等待处理', processing: '解析中', completed: '已完成', failed: '解析失败' }

export function MaterialsPage() {
  const { route, setRoute } = useProcessingRoute()
  const [query, setQuery] = useSearchParams()
  const location = useLocation()
  const targetBookId = query.get('notebook') ?? ''
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([])
  const [booksLoading, setBooksLoading] = useState(true)
  const [rootOpen, setRootOpen] = useState(false)
  const {
    course,
    courseContentLoading,
    materials,
    selectedMaterialId,
    setSelectedMaterialId,
    pages,
    selectedPageNumber,
    setSelectedPageNumber,
    job,
    busy,
    uploadMaterial,
    retryMaterial,
    reparseMaterial,
    requestOCR,
    refreshCurrentMaterials,
  } = useWorkspace()
  const [file, setFile] = useState<File>()
  const [lectureTitle, setLectureTitle] = useState('第 1 讲')
  const [topicTitle, setTopicTitle] = useState('')
  const [allowDuplicate, setAllowDuplicate] = useState(false)
  const [webSources, setWebSources] = useState<import('../types').WebSource[]>([])
  const [deletedMaterials, setDeletedMaterials] = useState<import('../types').Material[]>([])
  const [materialActionError, setMaterialActionError] = useState<string>()
  const [coverage, setCoverage] = useState<Coverage>()
  const [pageEvidence, setPageEvidence] = useState<PageEvidence>()
  const [capabilities, setCapabilities] = useState<Capabilities>()
  const [materialRemoval, setMaterialRemoval] = useState<{ id: string; impact: DeletionPreview }>()
  const [deletionPreviewingId, setDeletionPreviewingId] = useState<string>()
  const [deletingMaterialId, setDeletingMaterialId] = useState<string>()
  const [startLearningCourse, setStartLearningCourse] = useState<ForestCourse>()
  const [startingLearning, setStartingLearning] = useState(false)
  const currentCourseId = useRef(course?.id)
  currentCourseId.current = course?.id
  useEffect(() => { setStartLearningCourse(undefined) }, [course?.id])
  useEffect(() => {
    let active = true
    setNotebooks([]); setBooksLoading(true)
    if (!course) return () => { active = false }
    void api.listNotebooks(course.id).then(items => {
      if (!active) return
      setNotebooks(items)
      if (!targetBookId && items.length === 1) setQuery({ notebook: items[0].id }, { replace: true, state: location.state })
    }).catch((cause: unknown) => { if (active) setMaterialActionError(cause instanceof Error ? cause.message : '笔记本列表读取失败') })
      .finally(() => { if (active) setBooksLoading(false) })
    return () => { active = false }
  }, [course?.id, targetBookId])
  useEffect(() => { setRootOpen(false) }, [targetBookId])
  const targetBook = notebooks.find(book => book.id === targetBookId)

  useEffect(() => {
    let active = true
    void api.getCapabilities().then((value) => { if (active) setCapabilities(value) }).catch(() => { if (active) setCapabilities(undefined) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    if (!course) return () => { active = false }
    void api.listDeletedMaterials(course.id).then((items) => { if (active) setDeletedMaterials(items) }).catch(() => { if (active) setDeletedMaterials([]) })
    return () => { active = false }
  }, [course?.id, materials])

  async function deleteMaterial(id: string) {
    if (deletionPreviewingId || deletingMaterialId) return
    try {
      setDeletionPreviewingId(id)
      const impact = await api.previewMaterialDeletion(id)
      if (impact.active_jobs) throw new Error('资料仍在处理中，请完成后再移除。')
      setMaterialRemoval({ id, impact })
      setMaterialActionError(undefined)
    } catch (cause) { setMaterialActionError(cause instanceof Error ? cause.message : '资料移除预览失败') }
    finally { setDeletionPreviewingId(undefined) }
  }

  async function confirmMaterialRemoval() {
    if (!materialRemoval || deletingMaterialId) return
    try {
      setDeletingMaterialId(materialRemoval.id)
      await api.deleteMaterial(materialRemoval.id)
      setMaterialRemoval(undefined)
      await refreshCurrentMaterials()
      setMaterialActionError(undefined)
    } catch (cause) { setMaterialActionError(cause instanceof Error ? cause.message : '资料移除失败') }
    finally { setDeletingMaterialId(undefined) }
  }

  async function restoreMaterial(id: string) {
    try { await api.restoreMaterial(id); await refreshCurrentMaterials(); setMaterialActionError(undefined) }
    catch (cause) { setMaterialActionError(cause instanceof Error ? cause.message : '资料恢复失败') }
  }

  async function handleUpload(event: FormEvent) {
    event.preventDefault()
    if (!file || !targetBook) return
    try {
      await uploadMaterial(file, lectureTitle, targetBook.id, topicTitle, allowDuplicate, undefined, route)
      setFile(undefined)
      setAllowDuplicate(false)
      if (course) {
        void api.getForest().then(({ courses }) => { if (currentCourseId.current === course.id) setStartLearningCourse(courses.find((item) => item.course_id === course.id && item.learning_state === 'planned')) }).catch(() => { /* Upload success remains visible even if the optional forest prompt is unavailable. */ })
      }
    } catch {
      // The workspace displays the API error; keep the file for a corrected retry.
    }
  }

  const selectedPage = pages.find((page) => page.page_number === selectedPageNumber)
  const uploadLimit = capabilities?.processing_routes?.[route ?? capabilities.default_processing_route ?? 'standard']?.max_upload_bytes ?? capabilities?.max_upload_bytes

  async function startLearning() {
    if (!startLearningCourse) return
    setStartingLearning(true)
    try { await api.updateForestCourse(startLearningCourse.course_id, { expected_revision: startLearningCourse.revision, learning_state: 'learning' }); setStartLearningCourse(undefined) }
    catch (cause) { setMaterialActionError(cause instanceof Error ? cause.message : '学习状态保存失败') }
    finally { setStartingLearning(false) }
  }

  useEffect(() => {
    if (!selectedMaterialId) { setWebSources([]); return }
    let active = true
    void api.listMaterialWebSources(selectedMaterialId).then((items) => { if (active) setWebSources(items) }).catch(() => { if (active) setWebSources([]) })
    void api.getCoverage(selectedMaterialId).then((value) => { if (active) setCoverage(value) }).catch(() => { if (active) setCoverage(undefined) })
    return () => { active = false }
  }, [selectedMaterialId])

  useEffect(() => {
    if (!selectedMaterialId || selectedPageNumber === undefined) { setPageEvidence(undefined); return }
    let active = true
    void api.getPageEvidence(selectedMaterialId, selectedPageNumber).then((value) => { if (active) setPageEvidence(value) }).catch(() => { if (active) setPageEvidence(undefined) })
    return () => { active = false }
  }, [selectedMaterialId, selectedPageNumber])

  return (
    <div className="feature-page page-enter">
      <header className="page-heading-block compact-heading">
        <div><span className="eyebrow">{course?.name ?? '当前课程'}</span><h1>课程资料</h1><p>上传支持的课件格式，检查解析状态、位置证据与来源覆盖。</p></div>
        <span className="page-count-pill">{materials.length} 份资料</span>
      </header>

      <form className="material-upload-card" onSubmit={(event) => void handleUpload(event)}>
        <ProcessingRouteControl value={route} onChange={setRoute} disabled={busy} />
        <label>目标笔记本<select aria-label="目标笔记本" value={targetBook?.id ?? ''} disabled={booksLoading || busy} onChange={event => setQuery({ notebook: event.target.value }, { state: location.state })}><option value="" disabled>请选择本课程的笔记本</option>{notebooks.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
        {!booksLoading && !notebooks.length && <p>此课程尚无笔记本。<button type="button" onClick={() => setRootOpen(true)}>新建笔记本</button></p>}
        {!booksLoading && targetBookId && !targetBook && <p role="alert">目标笔记本不存在或属于其他课程，请重新选择。</p>}
        <div className="upload-card-heading"><span className="upload-card-icon">＋</span><div><h2>添加课程资料</h2><p>支持 {(capabilities?.allowed_extensions ?? ['.pptx', '.pdf', '.docx']).join('、')}，单文件上限 {uploadLimit ? `${Math.round(uploadLimit / 1024 / 1024)} MB` : '由后端配置'}。</p><small>{route === 'llm' ? '扫描页、图表和公式由当前模型读取，保留原页证据。' : capabilities?.ocr.status === 'ready' ? `扫描页可使用 OCR，每次最多 ${capabilities.ocr.max_pages} 页。` : '扫描页会标记为待检查，不会生成虚构文本。'}</small></div></div>
        <div className="material-upload-fields">
          <label className="material-file-field"><span>{file ? file.name : '选择课件文件'}</span><input type="file" accept={(capabilities?.allowed_extensions ?? ['.pptx', '.pdf', '.docx']).join(',')} onChange={(event) => setFile(event.target.files?.[0])} /></label>
          <button className="primary-button" type="submit" disabled={!file || busy || !targetBook}>{busy ? '上传中…' : '上传并解析'}</button>
        </div>
        <details className="material-upload-options">
          <summary>设置讲次信息</summary>
          <div className="material-upload-metadata">
            <label>讲次名称<input value={lectureTitle} onChange={(event) => setLectureTitle(event.target.value)} maxLength={200} placeholder="例如：第 1 讲 · 软件生命周期" /></label>
            <label>章节 / 主题（可选）<input value={topicTitle} onChange={(event) => setTopicTitle(event.target.value)} maxLength={200} placeholder="例如：第一章 · 软件生命周期" /></label>
            <label className="material-duplicate-option"><input type="checkbox" checked={allowDuplicate} onChange={(event) => setAllowDuplicate(event.target.checked)} />相同文件作为新讲次导入</label>
          </div>
        </details>
      </form>
      {rootOpen && course && <NotebookRootMenu courseId={course.id} courseName={course.name} onClose={() => setRootOpen(false)} returnState={location.state} />}

      {startLearningCourse && <div className="materials-forest-start"><span>已上传第一讲，要将森林中的这门课设为“在学”吗？</span><button type="button" disabled={startingLearning} onClick={() => void startLearning()}>{startingLearning ? '保存中…' : '开始学习'}</button><button type="button" disabled={startingLearning} onClick={() => setStartLearningCourse(undefined)}>稍后</button></div>}

      <ProcessingStatus job={job?.material_id === selectedMaterialId ? job : undefined} material={materials.find((item) => item.id === selectedMaterialId)} />
      {materialActionError && <p className="form-error" role="alert">{materialActionError}</p>}
      {deletedMaterials.length > 0 && <details className="deleted-materials-disclosure"><summary>可恢复的资料 · {deletedMaterials.length}</summary>{deletedMaterials.map((material) => <div key={material.id}><span>{material.lecture_title} · {material.original_filename}</span><button className="text-button" onClick={() => void restoreMaterial(material.id)}>恢复资料</button></div>)}</details>}

      <section className="materials-list-section">
        <div className="section-heading-row"><div><span className="eyebrow">当前课程</span><h2>已上传资料</h2></div></div>
        {courseContentLoading ? <div className="page-loading" role="status">正在读取课程资料…</div> : materials.length === 0 ? (
          <EmptyState icon="▱" title="还没有课程资料" description="选择 PPTX、PDF 或 DOCX 上传后，解析状态和课件位置会显示在这里。" />
        ) : (
          <div className="materials-browser">
            <div className="materials-list" aria-label="课程资料列表">
              {materials.map((material) => (
                <div className="material-row" key={material.id}>
                  <button className={`material-list-item ${selectedMaterialId === material.id ? 'material-list-item-active' : ''}`} onClick={() => setSelectedMaterialId(material.id)}>
                    <span className="material-list-icon">▱</span>
                    <span className="material-list-copy"><strong>{material.lecture_title}</strong><small>{material.topic_title ? `${material.topic_title} · ` : ''}{material.original_filename} · {material.page_count} 页</small><time dateTime={material.created_at}>上传于 {new Date(material.created_at).toLocaleString('zh-CN')}</time></span>
                    <span className={`status-pill status-pill-${material.status}`}>{statusLabels[material.status] ?? material.status}</span>
                  </button>
                  {material.status === 'failed' && material.asset_id && material.processing_route !== 'llm' && <button className="material-retry-action" onClick={() => {
                    void api.switchAssetProcessingRoute(material.asset_id!, 'llm').then(() => refreshCurrentMaterials()).catch(cause => setMaterialActionError(String(cause)))
                  }}>改用全程 AI</button>}
                  {['pending', 'processing'].includes(material.status) && material.asset_id && material.processing_route === 'llm' && <button className="text-button" onClick={() => {
                    void api.cancelAssetProcessing(material.asset_id!).then(() => refreshCurrentMaterials()).catch(cause => setMaterialActionError(String(cause)))
                  }}>取消读取</button>}
                  {(material.status === 'failed' || material.status === 'completed') && <details className="material-row-actions"><summary>更多</summary>{material.status === 'failed' && <button className="material-retry-action" onClick={() => void retryMaterial(material.id)}>重试解析</button>}{material.status === 'completed' && <button className="material-retry-action" onClick={() => void reparseMaterial(material.id)}>重新解析</button>}<button className="text-button" disabled={Boolean(deletionPreviewingId || deletingMaterialId)} onClick={() => void deleteMaterial(material.id)}>{deletionPreviewingId === material.id ? '准备移除…' : '移除资料'}</button></details>}
                </div>
              ))}
            </div>

            <div className="material-pages-panel">
              <div className="panel-heading"><strong>逐页解析预览</strong><span>{pages.length} 页</span></div>
              {!selectedMaterialId ? (
                <div className="inline-empty">选择一份资料查看解析页面。</div>
              ) : pages.length === 0 ? (
                <div className="inline-empty">资料解析完成后，页面文本会显示在这里。</div>
              ) : (
                <div className="material-page-list">
                  {pages.map((page) => (
                    <button className={`material-page-item ${selectedPageNumber === page.page_number ? 'material-page-item-active' : ''}`} key={page.id} onClick={() => setSelectedPageNumber(page.page_number)}>
                      <span className="page-number-badge">{String(page.page_number).padStart(2, '0')}</span>
                      <span><strong>{page.location_label || `第 ${page.page_number} 页`} · {page.title || '未识别标题'}</strong><small>{page.raw_text ? `${page.raw_text.slice(0, 120)}${page.raw_text.length > 120 ? '…' : ''}` : page.warning || '本位置未识别到文本'}</small></span>
                    </button>
                  ))}
                </div>
              )}
              {selectedPage && <article className="material-page-detail"><span className="eyebrow">{selectedPage.location_label || `第 ${selectedPage.page_number} 页`} · {selectedPage.extraction_method}</span><h3>{selectedPage.title || '未识别标题'}</h3><p>{selectedPage.raw_text || '本位置没有可展示的文本。'}</p>{selectedPage.warning && <small className="form-error">{selectedPage.warning}</small>}{selectedPage.parse_status === 'ocr_candidate' && <button className="secondary-button" type="button" onClick={() => void requestOCR(selectedMaterialId!)}>请求 OCR</button>}{pageEvidence?.blocks.length ? <div className="page-block-list" aria-label="页面结构化块">{pageEvidence.blocks.map((block) => <div className="page-block-item" key={block.id}><strong>{block.block_type} · {block.location_label || `块 ${block.position + 1}`} · {block.extraction_method}</strong><small>{block.content || block.warning || '该对象没有可展示文本。'}</small>{block.note_titles.length > 0 && <small>关联笔记：{block.note_ids.map((id, i) => <Link key={id} to={`/courses/${course?.id}/notebooks/${id}`}>{block.note_titles[i] ?? '打开笔记'} </Link>)}</small>}</div>)}</div> : null}{pageEvidence?.note_titles.length ? <small className="evidence-empty">本位置关联笔记：{pageEvidence.note_ids.map((id, i) => <Link key={id} to={`/courses/${course?.id}/notebooks/${id}`}>{pageEvidence.note_titles[i] ?? '打开笔记'} </Link>)}</small> : null}</article>}
              {coverage && <details className="material-coverage-disclosure"><summary>查看来源覆盖</summary><CoverageGrid coverage={coverage} onOpenPage={setSelectedPageNumber} /></details>}
              {selectedMaterialId && <details className="material-web-sources"><summary>联网补充来源 · {webSources.length}</summary>{webSources.length ? <div className="source-card-list">{webSources.map((source) => <a className="source-card" key={source.id} href={source.url} target="_blank" rel="noreferrer"><span className="source-card-icon">↗</span><span className="source-card-body"><small className="source-card-meta">{source.site_name} · 检索于 {new Date(source.retrieved_at).toLocaleDateString('zh-CN')}</small><strong>{source.title}</strong><small>{source.snippet}</small></span></a>)}</div> : <p className="evidence-empty">此资料没有已保存的联网补充来源。搜索未配置或未找到可靠结果时不会显示虚构来源。</p>}</details>}
            </div>
          </div>
        )}
      </section>
      {materialRemoval && <ConfirmDialog
        eyebrow="课程资料管理"
        title={`移除“${materials.find((item) => item.id === materialRemoval.id)?.lecture_title ?? '这份资料'}”？`}
        description="资料会从当前列表隐藏，操作前自动备份；之后可在可恢复资料中恢复。受保护的用户笔记不会被删除。"
        confirmLabel="确认移除资料"
        cancelLabel="保留资料"
        tone="danger"
        pending={Boolean(deletingMaterialId)}
        pendingLabel="正在移除…"
        error={materialActionError}
        onConfirm={() => void confirmMaterialRemoval()}
        onCancel={() => setMaterialRemoval(undefined)}
      >
        <div className="deletion-impact" aria-label="移除影响范围">
          <span><strong>{materialRemoval.impact.pages}</strong><small>个页面</small></span>
          <span><strong>{materialRemoval.impact.source_refs}</strong><small>条来源</small></span>
          <span><strong>{materialRemoval.impact.user_notes_protected}</strong><small>条受保护笔记</small></span>
        </div>
      </ConfirmDialog>}
    </div>
  )
}
