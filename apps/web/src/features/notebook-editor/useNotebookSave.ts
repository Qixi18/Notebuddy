import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { stableStringify, type DocNode, type NotebookDocumentResponse } from './document'
import { clearDraft, writeDraft, type NotebookDraft } from './draftStore'

export type NotebookSaveState = 'saved' | 'unsaved' | 'saving' | 'error' | 'conflict'

const AUTOSAVE_DELAY = 850
const DRAFT_DELAY = 500

export function useNotebookSave({ courseId, notebookId, onDirtyChange }: {
  courseId: string | undefined
  notebookId: string | undefined
  onDirtyChange?: (dirty: boolean) => void
}) {
  const [state, setState] = useState<NotebookSaveState>('saved')
  const [error, setError] = useState<string>()
  const [revision, setRevision] = useState(0)
  const [lastSavedAt, setLastSavedAt] = useState<string>()
  const [conflictOpen, setConflictOpen] = useState(false)
  const contentRef = useRef<DocNode | null>(null)
  const savedSnapshotRef = useRef<string>('')
  const revisionRef = useRef(0)
  const inFlightRef = useRef(false)
  const conflictRef = useRef(false)
  const failedRef = useRef(false)
  const saveTimer = useRef<number | undefined>(undefined)
  const draftTimer = useRef<number | undefined>(undefined)
  const draftOperations = useRef<Promise<void>>(Promise.resolve())
  const mountedRef = useRef(true)
  const onDirtyChangeRef = useRef(onDirtyChange)
  onDirtyChangeRef.current = onDirtyChange

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
      if (draftTimer.current) window.clearTimeout(draftTimer.current)
    }
  }, [])

  const queueDraftOperation = useCallback((operation: () => Promise<void>) => {
    draftOperations.current = draftOperations.current.catch(() => undefined).then(operation)
    void draftOperations.current.catch(() => undefined)
  }, [])

  const persistDraft = useCallback((content: DocNode, immediate = false) => {
    if (!courseId || !notebookId) return
    if (draftTimer.current) window.clearTimeout(draftTimer.current)
    const revision = revisionRef.current
    const write = () => queueDraftOperation(() => writeDraft(courseId, notebookId, content, revision))
    if (immediate) write()
    else draftTimer.current = window.setTimeout(write, DRAFT_DELAY)
  }, [courseId, notebookId, queueDraftOperation])

  const isDirty = useCallback(() => {
    if (!contentRef.current) return false
    return stableStringify(contentRef.current) !== savedSnapshotRef.current
  }, [])

  // Route changes unmount the editor without firing `beforeunload`. Preserve
  // the current body immediately so a fast Notebook switch cannot cancel the
  // only pending draft write.
  useEffect(() => () => {
    if (isDirty() && contentRef.current) persistDraft(contentRef.current, true)
  }, [isDirty, persistDraft])

  const saveNow = useCallback(async (): Promise<boolean> => {
    if (!courseId || !notebookId || !contentRef.current) return false
    if (inFlightRef.current || conflictRef.current) return false
    const snapshot = stableStringify(contentRef.current)
    if (snapshot === savedSnapshotRef.current) {
      setState('saved')
      onDirtyChangeRef.current?.(false)
      return true
    }
    inFlightRef.current = true
    setState('saving')
    setError(undefined)
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    try {
      const saved = courseId === 'unbound'
        ? await api.saveUnboundNotebookDocument(notebookId, contentRef.current, revisionRef.current)
        : await api.saveNotebookDocument(courseId, notebookId, contentRef.current, revisionRef.current)
      revisionRef.current = saved.revision
      savedSnapshotRef.current = snapshot
      failedRef.current = false
      const stillDirty = stableStringify(contentRef.current) !== snapshot
      if (stillDirty) {
        persistDraft(contentRef.current, true)
      } else if (mountedRef.current) {
        if (draftTimer.current) window.clearTimeout(draftTimer.current)
        queueDraftOperation(() => clearDraft(courseId, notebookId))
      }
      if (!mountedRef.current) return true
      setRevision(saved.revision)
      // Display when this editor confirmed the successful save. The loaded
      // document still uses the server timestamp until a local save succeeds.
      setLastSavedAt(new Date().toISOString())
      setState(stillDirty ? 'unsaved' : 'saved')
      onDirtyChangeRef.current?.(stillDirty)
      if (stillDirty) {
        saveTimer.current = window.setTimeout(() => void saveNowRef.current(), 400)
      }
      return true
    } catch (cause) {
      failedRef.current = true
      if (contentRef.current) persistDraft(contentRef.current, true)
      if (!mountedRef.current) return false
      if (cause instanceof ApiError && cause.status === 409) {
        conflictRef.current = true
        setConflictOpen(true)
        setState('conflict')
        setError('这篇笔记已在另一个窗口被更新。本地草稿已保留，请选择如何处理。')
      } else {
        setState('error')
        setError(cause instanceof Error ? cause.message : '笔记保存失败，请检查网络后重试。')
      }
      onDirtyChangeRef.current?.(true)
      return false
    } finally {
      inFlightRef.current = false
    }
  }, [courseId, notebookId, persistDraft, queueDraftOperation])
  const saveNowRef = useRef(saveNow)
  saveNowRef.current = saveNow

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => void saveNowRef.current(), AUTOSAVE_DELAY)
  }, [])

  const markEdited = useCallback((content: DocNode) => {
    contentRef.current = content
    if (conflictRef.current) {
      persistDraft(content)
      return
    }
    failedRef.current = false
    if (stableStringify(content) === savedSnapshotRef.current) {
      setState('saved')
      onDirtyChangeRef.current?.(false)
      return
    }
    setState((current) => current === 'saving' ? 'saving' : 'unsaved')
    onDirtyChangeRef.current?.(true)
    persistDraft(content)
    scheduleSave()
  }, [persistDraft, scheduleSave])

  const reset = useCallback((content: DocNode, nextRevision: number, updatedAt?: string) => {
    contentRef.current = content
    savedSnapshotRef.current = stableStringify(content)
    revisionRef.current = nextRevision
    conflictRef.current = false
    failedRef.current = false
    setRevision(nextRevision)
    setLastSavedAt(updatedAt)
    setState('saved')
    setError(undefined)
    setConflictOpen(false)
    onDirtyChangeRef.current?.(false)
  }, [])

  const restoreDraft = useCallback((draft: NotebookDraft) => {
    if (!courseId || !notebookId || draft.key !== `notebook:${courseId}:${notebookId}`) return
    // The draft's revision is the version it was edited against. Keeping the
    // freshly loaded server revision here would silently overwrite newer text.
    revisionRef.current = draft.revision
    setRevision(draft.revision)
    markEdited(draft.content)
  }, [courseId, notebookId, markEdited])

  const retry = useCallback(() => {
    if (conflictRef.current) return
    failedRef.current = false
    setError(undefined)
    void saveNowRef.current()
  }, [])

  const fetchServer = useCallback(async (): Promise<NotebookDocumentResponse | null> => {
    if (!courseId || !notebookId) return null
    try {
      return courseId === 'unbound'
        ? await api.getUnboundNotebookDocument(notebookId)
        : await api.getNotebookDocument(courseId, notebookId)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '服务器版本读取失败')
      return null
    }
  }, [courseId, notebookId])

  const applyServer = useCallback((document: NotebookDocumentResponse) => {
    reset(document.content, document.revision, document.updated_at)
  }, [reset])

  const overwriteServer = useCallback(async () => {
    if (!courseId || !notebookId || !contentRef.current) return
    const latest = await fetchServer()
    if (!latest) return
    revisionRef.current = latest.revision
    conflictRef.current = false
    setConflictOpen(false)
    setError(undefined)
    setState('unsaved')
    await saveNowRef.current()
  }, [courseId, fetchServer, notebookId])

  const keepLocalDraft = useCallback(() => {
    if (!courseId || !notebookId || !contentRef.current) return
    persistDraft(contentRef.current, true)
    setConflictOpen(false)
    setState('unsaved')
    setError('本地草稿已保留。自动保存已暂停，处理完冲突后再继续保存。')
  }, [courseId, notebookId, persistDraft])

  useEffect(() => {
    if (!courseId || !notebookId) return
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!isDirty()) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [courseId, isDirty, notebookId])

  const flush = useCallback(() => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    return saveNowRef.current()
  }, [])

  return {
    state, error, revision, lastSavedAt, conflictOpen, setConflictOpen,
    reset, restoreDraft, markEdited, saveNow: flush, retry, isDirty, getRevision: () => revisionRef.current,
    fetchServer, applyServer, overwriteServer, keepLocalDraft,
  }
}
