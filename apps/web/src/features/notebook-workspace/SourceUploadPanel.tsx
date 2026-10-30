import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../../api'
import type { NotebookGenerationJob, NotebookUploadBatch } from '../../types'
import { ProcessingRouteControl, useProcessingRoute } from '../notebook/useProcessingRoute'

const inputStatusLabels: Record<string, string> = {
  waiting_parse: '等待解析',
  parsing: '解析中',
  parse_failed: '解析未通过',
  ready: '已解析，等待生成',
  generating: '正在生成讲解',
  generation_failed: '生成失败',
  completed: '已写入笔记',
}

/** Upload PDF/images, follow parse + generation, then let the editor refresh. */
export function SourceUploadPanel({
  notebookId,
  onDocumentUpdated,
}: {
  notebookId: string
  onDocumentUpdated: (revision?: number) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const { route, setRoute } = useProcessingRoute()
  const [busy, setBusy] = useState(false)
  const [batch, setBatch] = useState<NotebookUploadBatch>()
  const [job, setJob] = useState<NotebookGenerationJob>()
  const [error, setError] = useState<string>()
  const [lastFiles, setLastFiles] = useState<string[]>([])
  const notified = useRef<number | undefined>(undefined)

  const poll = useCallback(async (batchId?: string) => {
    try {
      if (batchId) {
        const next = await api.getNotebookUploadBatch(notebookId, batchId)
        setBatch(next)
      }
      const jobs = await api.listNotebookGenerationJobs(notebookId)
      const latest = jobs[0]
      if (latest) setJob(latest)
      if (latest?.status === 'completed' && notified.current !== latest.base_document_revision) {
        notified.current = latest.base_document_revision
        onDocumentUpdated(latest.base_document_revision)
      }
      if (latest?.status === 'failed') setError(latest.error_message ?? '生成失败，请重试')
      if (latest?.error_code === 'parse_quality_insufficient' && latest.error_message) {
        setError(latest.error_message)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '处理状态读取失败')
    }
  }, [notebookId, onDocumentUpdated])

  useEffect(() => {
    if (!batch && !job) return
    const active = batch && ['parsing', 'generating', 'waiting_parse'].includes(batch.status)
    const jobActive = job && ['pending', 'processing'].includes(job.status)
    const relationsActive = batch?.relation_jobs?.some(item => ['pending', 'processing'].includes(item.status))
    if (!active && !jobActive && !relationsActive) return
    const timer = window.setInterval(() => { void poll(batch?.id) }, 1500)
    return () => window.clearInterval(timer)
  }, [batch, job, poll])

  async function upload(files: FileList | null) {
    if (!files?.length || busy) return
    setBusy(true)
    setError(undefined)
    const batchId = crypto.randomUUID()
    setLastFiles(Array.from(files).map((file) => file.name))
    try {
      for (const file of Array.from(files)) {
        await api.uploadNotebookAsset(notebookId, file, batchId, route)
      }
      const closed = await api.closeNotebookUploadBatch(notebookId, batchId)
      setBatch(closed)
      notified.current = undefined
      window.setTimeout(() => { void poll(batchId) }, 800)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '资料上传失败')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const jobLabel = job
    ? job.status === 'pending' ? '生成任务排队中'
      : job.status === 'processing' ? '正在生成讲解正文'
        : job.status === 'completed' ? '讲解已写入笔记正文'
          : job.status === 'failed' ? '生成失败'
            : job.status
    : undefined

  return (
    <section className="notebook-source-panel" aria-label="学习资料与生成状态">
      <div className="notebook-source-head">
        <strong>资料与生成</strong>
        <span>{busy ? '正在上传…' : '支持 PDF / PPTX / DOCX / PNG / JPG'}</span>
      </div>
      <input
        ref={input}
        type="file"
        accept=".pdf,.pptx,.docx,.png,.jpg,.jpeg"
        multiple
        hidden
        onChange={(event) => void upload(event.target.files)}
      />
      <ProcessingRouteControl value={route} onChange={setRoute} disabled={busy} />
      <button type="button" className="primary-button" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? '正在上传…' : '上传 PDF 或图片'}
      </button>
      {lastFiles.length > 0 && <p className="notebook-source-files">本次上传：{lastFiles.join('、')}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {batch && (
        <ul className="notebook-source-status">
          {batch.inputs.map((item) => (
            <li key={item.asset_id} className={`status-${item.status}`}>
              <span>{item.processing_route === 'llm' && ['waiting_parse', 'parsing'].includes(item.status) ? `AI 读取 · ${item.completed_pages ?? 0} / ${item.total_pages ?? 0} 页` : inputStatusLabels[item.status] ?? item.status}</span>
              {item.error_message && <small>{item.error_message}</small>}
              {item.status === 'parse_failed' && item.processing_route !== 'llm' && <button type="button" onClick={() => {
                void api.switchAssetProcessingRoute(item.asset_id, 'llm').then(() => poll(batch.id)).catch(cause => setError(String(cause)))
              }}>改用全程 AI</button>}
              {['waiting_parse', 'parsing'].includes(item.status) && item.processing_route === 'llm' && <button type="button" onClick={() => {
                void api.cancelAssetProcessing(item.asset_id).then(() => poll(batch.id)).catch(cause => setError(String(cause)))
              }}>取消读取</button>}
            </li>
          ))}
        </ul>
      )}
      {jobLabel && (
        <p className="notebook-source-job">
          {jobLabel}
          {job?.generator === 'offline-extractive' && <small>（离线结构化整理，未调用模型）</small>}
          {job?.plan && <small>新增 {job.plan.new_count ?? 0} · 补充 {job.plan.extend_count ?? 0} · 跳过 {job.plan.skip_count ?? 0}</small>}
        </p>
      )}
      {batch?.relation_jobs?.map(item => <p key={item.id} role="status">知识联系：{item.status === 'completed' ? '分析完成' : item.status === 'failed' ? item.error_message ?? '分析失败，笔记已保留' : '正在分析藤蔓关系'}{item.status === 'failed' && <button type="button" onClick={() => { void api.retryForestJob(item.id).then(() => poll(batch.id)).catch(cause => setError(String(cause))) }}>重试联系分析</button>}</p>)}
      {job?.status === 'failed' && (
        <button type="button" className="secondary-button" onClick={() => {
          void api.retryNotebookGenerationJob(notebookId, job.id).then(next => {
            setJob(next)
            setError(undefined)
          }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '重试失败'))
        }}>重试生成</button>
      )}
    </section>
  )
}
