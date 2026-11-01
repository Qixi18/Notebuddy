import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'

import { api } from '../../../api'
import type { Material, NotebookGenerationJob, NotebookUploadBatch } from '../../../types'
import type { DocumentRefreshResult } from './useNotebookDocument'

export type UploadProgressPhase = 'uploading' | 'parsing' | 'generating' | 'refreshing' | 'complete' | 'complete-protected' | 'failed'
export type UploadProgressErrorKind = 'upload' | 'parse' | 'generation' | 'refresh'
const UNSAVED_GENERATION_MESSAGE = '当前有未保存的本地编辑，已保留草稿；保存后可重新载入最新内容。'

export type UploadProgressState = {
  phase: UploadProgressPhase
  batchId?: string
  fileNames: string[]
  message?: string
  errorKind?: UploadProgressErrorKind
}

export function uploadBatchFailureMessage(batch: NotebookUploadBatch): { message: string; errorKind: UploadProgressErrorKind } {
  const parseFailures = batch.inputs.filter((input) => input.status === 'parse_failed').length
  const generationFailures = batch.inputs.filter((input) => input.status === 'generation_failed').length
  if (parseFailures && generationFailures) return {
    message: `${parseFailures} 份资料解析失败，${generationFailures} 份笔记生成失败。可重试失败项。`, errorKind: 'parse',
  }
  if (parseFailures) return { message: `${parseFailures} 份资料解析失败，可重试。`, errorKind: 'parse' }
  if (generationFailures) return { message: `${generationFailures} 份笔记生成失败，可重试。`, errorKind: 'generation' }
  return { message: '部分资料未能处理完成，可重试失败项。', errorKind: 'parse' }
}

/**
 * Notebook 上传批次与生成任务：幂等批次、轮询、进度提示、失败重试。
 *
 * 正文刷新通过 `onRefresh` 回调交给正文 hook，两边不互相 import，避免
 * "生成侧改正文" 这条最容易丢数据的耦合（路线图 §5.2 第 4 条）。
 */
export function useNotebookGeneration({
  notebookId, courseId, isUnbound, loaded, bookMaterials, refreshCurrentMaterials,
  uploadMaterial, reloadOutline, onRefresh, refreshIfNewer, onNotice, processingRoute,
}: {
  notebookId?: string
  courseId: string | null
  isUnbound: boolean
  loaded: boolean
  bookMaterials: Material[]
  refreshCurrentMaterials: () => Promise<unknown>
  uploadMaterial: (
    file: File, lectureTitle: string, notebookId: string, topicTitle?: string,
    allowDuplicate?: boolean, batchId?: string, processingRoute?: 'standard' | 'llm',
  ) => Promise<unknown>
  reloadOutline: () => Promise<void>
  onRefresh: (batchId: string) => Promise<DocumentRefreshResult>
  /** 后台生成完成后刷新正文；返回 dirty 表示有未保存修改、已保留草稿 */
  refreshIfNewer: () => Promise<'updated' | 'unchanged' | 'dirty' | 'failed'>
  onNotice: (message: string) => void
  processingRoute?: 'standard' | 'llm'
}) {
  const [generationJob, setGenerationJob] = useState<NotebookGenerationJob | null>(null)
  const [generationBusy, setGenerationBusy] = useState(false)
  const [generationError, setGenerationError] = useState<string>()
  const [uploadBatchId, setUploadBatchId] = useState<string>()
  const [uploadBatch, setUploadBatch] = useState<NotebookUploadBatch | null>(null)
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null)
  const [uploadError, setUploadError] = useState<string>()
  const [allowDuplicateUploads, setAllowDuplicateUploads] = useState(false)
  const uploadCompletionStartedRef = useRef<string | undefined>(undefined)
  const uploadProgressTimerRef = useRef<number | undefined>(undefined)

  const uploadBatchGenerationJobIds = uploadBatch?.generation_jobs.map((job) => job.id).join('|') ?? ''

  const finishUploadProgress = useCallback((batchId: string, message?: string, protectedEdits = false) => {
    setUploadProgress((current) => current?.batchId === batchId
      ? { ...current, phase: protectedEdits ? 'complete-protected' : 'complete', ...(message ? { message } : {}) }
      : current)
    if (uploadProgressTimerRef.current) window.clearTimeout(uploadProgressTimerRef.current)
    uploadProgressTimerRef.current = window.setTimeout(() => {
      setUploadProgress((current) => current?.batchId === batchId ? null : current)
    }, 1800)
  }, [])

  useEffect(() => () => {
    if (uploadProgressTimerRef.current) window.clearTimeout(uploadProgressTimerRef.current)
  }, [])

  const relationsActive = uploadBatch?.relation_jobs?.some(item => ['pending', 'processing'].includes(item.status)) ?? false
  useEffect(() => {
    if (!notebookId || !uploadBatch?.id || !relationsActive) return
    let active = true
    const timer = window.setInterval(() => {
      void api.getNotebookUploadBatch(notebookId, uploadBatch.id).then(next => { if (active) setUploadBatch(next) }).catch(() => {})
    }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [notebookId, uploadBatch?.id, relationsActive])

  /* 进入页面时接管最近一个未结束批次：刷新页面后进度提示不能凭空消失。 */
  useEffect(() => {
    if (!loaded || !notebookId) return
    let active = true
    void api.listNotebookUploadBatches(notebookId).then((batches) => {
      if (!active || !batches.length) return
      const activeBatch = batches.find((batch) => ['open', 'waiting_parse', 'parsing', 'generating', 'partial_failure'].includes(batch.status))
      const current = activeBatch ?? batches[0]
      setUploadBatch(current)
      setUploadBatchId(current.id)
      if (activeBatch) {
        if (activeBatch.status === 'partial_failure') {
          const failure = uploadBatchFailureMessage(activeBatch)
          setUploadProgress({ batchId: activeBatch.id, phase: 'failed', fileNames: [], ...failure })
        } else {
          setUploadProgress({ batchId: activeBatch.id, phase: activeBatch.status === 'generating' ? 'generating' : 'parsing', fileNames: [] })
        }
      }
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
    const batch = uploadBatch
    if (!batch || !uploadProgress?.batchId || uploadProgress.batchId !== batch.id) return
    if (batch.status === 'partial_failure') {
      const failure = uploadBatchFailureMessage(batch)
      setUploadProgress((current) => {
        if (current?.batchId !== batch.id) return current
        if (current.phase === 'failed' && current.errorKind === failure.errorKind && current.message === failure.message) return current
        return { ...current, phase: 'failed', ...failure }
      })
    } else if (batch.status === 'generating') {
      setUploadProgress((current) => current?.batchId === batch.id && current.phase !== 'generating'
        ? { ...current, phase: 'generating', errorKind: undefined }
        : current)
    } else if (batch.status === 'completed') {
      setUploadProgress((current) => current?.batchId === batch.id && current.phase !== 'refreshing' && current.phase !== 'complete' && current.phase !== 'complete-protected'
        ? { ...current, phase: 'refreshing', errorKind: undefined }
        : current)
    } else if (['open', 'waiting_parse', 'parsing'].includes(batch.status)) {
      setUploadProgress((current) => current?.batchId === batch.id && current.phase !== 'parsing'
        ? { ...current, phase: 'parsing', errorKind: undefined }
        : current)
    }
  }, [uploadBatch, uploadProgress?.batchId])

  /* 批次完成 → 交给正文 hook 安全刷新 → 由结果决定进度提示（成功/保留草稿/失败）。 */
  useEffect(() => {
    const batch = uploadBatch
    if (!batch || batch.status !== 'completed' || !uploadBatchId || batch.id !== uploadBatchId) return
    if (uploadCompletionStartedRef.current === batch.id) return
    uploadCompletionStartedRef.current = batch.id
    void onRefresh(batch.id).then((result) => {
      if (result.status === 'protected') finishUploadProgress(batch.id, result.message, true)
      else if (result.status === 'updated') finishUploadProgress(batch.id, result.message)
      else setUploadProgress((current) => current?.batchId === batch.id
        ? { ...current, phase: 'failed' as const, errorKind: 'refresh' as const, message: result.message }
        : current)
    })
  }, [finishUploadProgress, onRefresh, uploadBatch, uploadBatchId])

  /* 直接由生成任务触发的刷新（非上传批次）：生成完成后正文可能变新。 */
  useEffect(() => {
    if (!notebookId || !generationJob || !['pending', 'processing', 'cancel_requested'].includes(generationJob.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.getNotebookGenerationJob(notebookId, generationJob.id).then(async (job) => {
        if (!active) return
        setGenerationJob(job)
        if (job.status === 'completed' && generationJob.status !== 'completed') {
          const trackedByUploadBatch = uploadBatchGenerationJobIds.split('|').includes(job.id)
          /* 有未保存修改时保留草稿：这是「后台生成不能覆盖用户正在写的内容」的硬边界。 */
          const outcome = await refreshIfNewer()
          if (outcome === 'dirty') {
            const message = UNSAVED_GENERATION_MESSAGE
            onNotice(`学习笔记已生成。${message}`)
            if (trackedByUploadBatch && uploadBatch?.id) finishUploadProgress(uploadBatch.id, message, true)
            return
          }
          if (outcome === 'updated' && !trackedByUploadBatch) onNotice('AI 补充内容已追加到正式正文。')
          if (outcome === 'failed' && !trackedByUploadBatch) onNotice('AI 已完成；正文刷新失败，请手动重新加载页面。')
        }
      }).catch((cause: unknown) => {
        if (active) setGenerationError(cause instanceof Error ? cause.message : '生成状态读取失败')
      })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [finishUploadProgress, generationJob?.id, generationJob?.status, notebookId, onNotice, refreshIfNewer, uploadBatch?.id, uploadBatchGenerationJobIds])

  async function handleUploadMaterial(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!files.length || isUnbound || !courseId || !notebookId) return
    if (uploadProgressTimerRef.current) window.clearTimeout(uploadProgressTimerRef.current)
    setUploadError(undefined)
    setUploadProgress({ phase: 'uploading', fileNames: files.map((file) => file.name) })
    try {
      const batchId = crypto.randomUUID()
      const results: PromiseSettledResult<unknown>[] = []
      for (const file of files) {
        const lectureTitle = file.name.replace(/\.[^.]+$/, '').trim() || '新资料'
        try {
          results.push({ status: 'fulfilled', value: await uploadMaterial(
            file, lectureTitle, notebookId, '', allowDuplicateUploads, batchId, processingRoute,
          ) })
        } catch (reason) {
          results.push({ status: 'rejected', reason })
        }
      }
      const uploadFailures = results.filter((result) => result.status === 'rejected').length
      const uploadedFiles = files.filter((_, index) => results[index]?.status === 'fulfilled')
      await refreshCurrentMaterials()
      setAllowDuplicateUploads(false)
      await reloadOutline()
      if (uploadFailures < files.length) {
        const batch = await api.closeNotebookUploadBatch(notebookId, batchId)
        setUploadBatchId(batchId)
        setUploadBatch(batch)
        setUploadProgress({
          batchId,
          phase: batch.status === 'generating' ? 'generating' : batch.status === 'partial_failure' ? 'failed' : 'parsing',
          fileNames: uploadedFiles.map((file) => file.name),
          ...(uploadFailures ? { message: `${uploadedFiles.length} 份资料已上传，${uploadFailures} 份上传失败。` } : {}),
          ...(batch.status === 'partial_failure' ? uploadBatchFailureMessage(batch) : {}),
        })
        if (uploadFailures) setUploadError(`${uploadedFiles.length} 份资料已上传，${uploadFailures} 份上传失败。`)
      } else {
        setUploadError('所选资料均未成功上传。')
        setUploadProgress({ phase: 'failed', fileNames: files.map((file) => file.name), errorKind: 'upload', message: '所选资料均未成功上传。请重新选择文件后重试。' })
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '资料上传失败'
      setUploadError(message)
      setUploadProgress((current) => current?.phase === 'uploading'
        ? { ...current, phase: 'failed', errorKind: 'upload', message }
        : current)
    }
  }

  async function retryUploadProgress() {
    const progress = uploadProgress
    if (!progress || generationBusy) return
    if (progress.errorKind === 'upload' || !progress.batchId) {
      setUploadProgress(null)
      return 'pick-file' as const
    }
    if (progress.errorKind === 'refresh') {
      uploadCompletionStartedRef.current = undefined
      const result = await onRefresh(progress.batchId)
      if (result.status === 'protected') finishUploadProgress(progress.batchId, result.message, true)
      else if (result.status === 'updated') finishUploadProgress(progress.batchId, result.message)
      else setUploadProgress((current) => current?.batchId === progress.batchId
        ? { ...current, phase: 'failed', errorKind: 'refresh', message: result.message, fileNames: current?.fileNames ?? [] }
        : current)
      return 'done' as const
    }
    const batch = uploadBatch?.id === progress.batchId ? uploadBatch : null
    if (!batch || !notebookId) return 'done' as const
    const failedInputs = batch.inputs.filter((input) => input.status === 'parse_failed' || input.status === 'generation_failed')
    if (!failedInputs.length) return 'done' as const
    setGenerationBusy(true)
    setGenerationError(undefined)
    setUploadProgress((current) => current?.batchId === batch.id
      ? { ...current, phase: failedInputs.some((input) => input.status === 'parse_failed') ? 'parsing' : 'generating', errorKind: undefined, message: '正在重试失败项…' }
      : current)
    try {
      const generationJobIds = new Set<string>()
      for (const input of failedInputs) {
        if (input.status === 'parse_failed') {
          const material = bookMaterials.find((item) => item.asset_id === input.asset_id)
          if (!material) throw new Error('找不到解析失败的资料，请从侧栏重新上传。')
          if (material.status === 'failed') await api.retryMaterial(material.id)
          else if (!['pending', 'processing'].includes(material.status)) await api.reparseMaterial(material.id)
        } else if (input.generation_job_id) {
          generationJobIds.add(input.generation_job_id)
        } else {
          throw new Error('找不到笔记生成任务，请从资料侧栏检查状态。')
        }
      }
      for (const jobId of generationJobIds) {
        const retriedJob = await api.retryNotebookGenerationJob(notebookId, jobId)
        setGenerationJob(retriedJob)
      }
      await refreshCurrentMaterials()
      const nextBatch = await api.getNotebookUploadBatch(notebookId, batch.id)
      setUploadBatch(nextBatch)
      setUploadProgress((current) => current?.batchId === batch.id ? {
        ...current,
        phase: nextBatch.status === 'generating' ? 'generating' : 'parsing',
        errorKind: undefined,
        message: '失败项已重新排队。',
      } : current)
    } catch (cause) {
      setUploadProgress((current) => current?.batchId === batch.id ? {
        ...current,
        phase: 'failed',
        errorKind: failedInputs.some((input) => input.status === 'parse_failed') ? 'parse' : 'generation',
        message: cause instanceof Error ? cause.message : '重试失败，请从资料侧栏重试。',
      } : current)
    } finally { setGenerationBusy(false) }
    return 'done' as const
  }

  async function retryGenerationJob() {
    if (!notebookId || !generationJob) return
    setGenerationBusy(true)
    try {
      setGenerationJob(await api.retryNotebookGenerationJob(notebookId, generationJob.id))
    } catch (cause) {
      setGenerationError(cause instanceof Error ? cause.message : '重试失败')
    } finally { setGenerationBusy(false) }
  }

  async function retryRelationJob(jobId: string) {
    if (!notebookId || !uploadBatch) return
    try {
      await api.retryForestJob(jobId)
      setUploadBatch(await api.getNotebookUploadBatch(notebookId, uploadBatch.id))
    } catch (cause) {
      setGenerationError(cause instanceof Error ? cause.message : '重试联系分析失败')
    }
  }

  const aiReadingProgress = uploadBatch?.inputs.reduce((value, item) => item.processing_route === 'llm'
    ? { count: value.count + 1, done: value.done + (item.completed_pages ?? 0), total: value.total + (item.total_pages ?? 0) }
    : value, { count: 0, done: 0, total: 0 })

  const generationStatusCoveredByToast = Boolean(
    uploadProgress?.batchId && generationJob?.id && uploadBatchGenerationJobIds.split('|').includes(generationJob.id),
  )

  return {
    generationJob, setGenerationJob, generationBusy, generationError, setGenerationError,
    uploadBatchId, setUploadBatchId, uploadBatch, setUploadBatch, uploadProgress, setUploadProgress,
    uploadError, setUploadError, allowDuplicateUploads, setAllowDuplicateUploads,
    uploadCompletionStartedRef, uploadProgressTimerRef, uploadBatchGenerationJobIds,
    aiReadingProgress, generationStatusCoveredByToast, relationsActive,
    finishUploadProgress, handleUploadMaterial, retryUploadProgress, retryGenerationJob, retryRelationJob,
  }
}
