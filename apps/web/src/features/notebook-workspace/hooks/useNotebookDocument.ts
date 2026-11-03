import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

import type { NotebookDocumentResponse, NotebookRead } from '../../../types'
import {
  clearDraft, readDraft, type NotebookDraft,
} from '../../notebook-editor/draftStore'
import {
  normalizeDocument, stableStringify, type DocNode,
} from '../../notebook-editor/document'
import type { NotebookEditorHandle, SelectionAnchor } from '../../notebook-editor/NotebookEditor'
import { useNotebookSave } from '../../notebook-editor/useNotebookSave'
import type { NotebookIdentity } from '../adapters/notebookApiAdapter'

/** 上传完成后刷新正文的结果：进度提示由生成侧根据它决定，避免两处互相调用。 */
export type DocumentRefreshResult =
  | { status: 'updated'; message: string }
  | { status: 'protected'; message: string }
  | { status: 'failed'; message: string }

type NotebookDocumentApi = ReturnType<typeof import('../adapters/notebookApiAdapter').notebookApiAdapter>

/**
 * Notebook 正文的唯一读写边界：载入、草稿、revision/CAS 保存、历史/冲突处理。
 *
 * 拆出来的目的（路线图 §5.2 第 2 条）：把「正文」与「资料资源」「生成任务」分开，
 * 三者都只通过本 hook 暴露的 save/refresh 原语改正文，不再各自持有副本。
 */
export function useNotebookDocument({
  notebookId, courseId, notebookApi, editorRef, onNotice,
}: {
  notebookId?: string
  courseId: string | null
  notebookApi: NotebookDocumentApi
  editorRef: RefObject<NotebookEditorHandle | null>
  onNotice: (message: string) => void
}) {
  const [outline, setOutline] = useState<NotebookRead>()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState<DocNode>({ type: 'doc', content: [] })
  const [loaded, setLoaded] = useState(false)
  const [editorReady, setEditorReady] = useState(false)
  const [loadError, setLoadError] = useState<string>()
  const [documentWarning, setDocumentWarning] = useState<string>()
  const [titleError, setTitleError] = useState<string>()
  const [titleSaving, setTitleSaving] = useState(false)
  const [lastTitleSavedAt, setLastTitleSavedAt] = useState<string>()
  const [draftFound, setDraftFound] = useState<NotebookDraft | null>(null)
  const [conflictPreview, setConflictPreview] = useState<NotebookDocumentResponse | null>(null)
  const [editVersion, setEditVersion] = useState(0)

  const editorReadyRef = useRef(false)
  const pageActiveRef = useRef(true)
  const onNoticeRef = useRef(onNotice)
  onNoticeRef.current = onNotice

  const save = useNotebookSave({ courseId, notebookId })

  useEffect(() => {
    pageActiveRef.current = true
    return () => { pageActiveRef.current = false }
  }, [])

  useEffect(() => {
    if (!notebookId) return
    let active = true
    setLoaded(false)
    setLoadError(undefined)
    setOutline(undefined)
    setDocumentWarning(undefined)
    setDraftFound(null)
    setEditVersion(0)
    editorReadyRef.current = false
    setEditorReady(false)
    void Promise.all([notebookApi.getNotebook(), notebookApi.getDocument()])
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
  }, [courseId, notebookApi, notebookId])

  const handleChange = useCallback((doc: DocNode) => {
    if (!editorReadyRef.current) return
    setContent(doc)
    setEditVersion((value) => value + 1)
    save.markEdited(doc)
  }, [save])

  const insertAI = useCallback((text: string, mode: 'after' | 'replace', anchor: SelectionAnchor | null,
                                expectedRevision?: number, expectedEditVersion?: number) => {
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
  }, [editVersion, editorRef, save.revision])

  const adoptDocument = useCallback((document: DocNode, revision: number, updatedAt: string, expectedEditVersion: number) => {
    if (editVersion !== expectedEditVersion || save.isDirty() || save.revision !== revision - 1) return false
    const normalized = normalizeDocument(document)
    editorRef.current?.replaceContent(normalized)
    setContent(normalized)
    setEditVersion((value) => value + 1)
    save.reset(normalized, revision, updatedAt)
    return true
  }, [editVersion, editorRef, save.isDirty, save.reset, save.revision])

  async function renameTitle() {
    const nextTitle = title.trim()
    if (!notebookId || !outline || !nextTitle || nextTitle === outline.title || titleSaving) {
      if (!nextTitle) setTitle(outline?.title ?? '')
      return
    }
    setTitleSaving(true)
    setTitleError(undefined)
    try {
      const renamed = await notebookApi.rename(nextTitle)
      setOutline(renamed)
      setTitle((current) => current === nextTitle ? renamed.title : current)
      setLastTitleSavedAt(new Date().toISOString())
    } catch (cause) {
      setTitleError(cause instanceof Error ? cause.message : '笔记名称保存失败')
    } finally { setTitleSaving(false) }
  }

  async function reloadOutline() {
    setOutline(await notebookApi.getNotebook())
  }

  /** 替换编辑器正文并同步 revision：所有「服务端正文变了」的路径都必须走这里。 */
  const applyServerDocument = useCallback((document: NotebookDocumentResponse) => {
    const normalized = normalizeDocument(document.content)
    editorRef.current?.replaceContent(normalized)
    setContent(normalized)
    setEditVersion((value) => value + 1)
    setDocumentWarning(document.warning ?? undefined)
    save.reset(normalized, document.revision, document.updated_at)
  }, [editorRef, save.reset])

  /**
   * 生成/上传完成后的安全刷新：有未保存修改时绝不覆盖，只返回 protected。
   * 调用方（生成侧）据此决定进度提示，二者不再互相引用。
   */
  const refreshNotebookAfterUpload = useCallback(async (batchId: string): Promise<DocumentRefreshResult> => {
    void batchId
    if (!notebookId) return { status: 'failed', message: 'Notebook 未就绪。' }
    const dirtyMessage = '检测到未保存修改，已保留当前正文；保存后可重新载入最新内容。'
    if (save.isDirty()) {
      onNoticeRef.current(`学习笔记已生成。${dirtyMessage}`)
      return { status: 'protected', message: dirtyMessage }
    }
    try {
      const latest = await notebookApi.getDocument()
      if (!pageActiveRef.current) return { status: 'failed', message: '页面已离开。' }
      if (save.isDirty()) {
        onNoticeRef.current(`学习笔记已生成。${dirtyMessage}`)
        return { status: 'protected', message: dirtyMessage }
      }
      if (latest.revision > save.revision) {
        applyServerDocument(latest)
      }
      return { status: 'updated', message: '正文已更新。' }
    } catch (cause) {
      if (!pageActiveRef.current) return { status: 'failed', message: '页面已离开。' }
      return {
        status: 'failed',
        message: cause instanceof Error ? `笔记已生成，但正文载入失败：${cause.message}` : '笔记已生成，但正文载入失败。可重试载入。',
      }
    }
  }, [applyServerDocument, notebookApi, notebookId, save.isDirty, save.revision])

  function restoreDraft() {
    if (!draftFound) return
    const restored = normalizeDocument(draftFound.content)
    editorRef.current?.replaceContent(restored)
    setContent(restored)
    setEditVersion((value) => value + 1)
    save.restoreDraft({ ...draftFound, content: restored })
    setDraftFound(null)
    onNoticeRef.current('已恢复本地草稿，保存成功后会清除草稿副本。')
  }

  async function discardDraft() {
    setDraftFound(null)
    if (notebookId) await clearDraft(courseId, notebookId)
  }

  async function showServerVersion() {
    const latest = await save.fetchServer()
    if (latest) setConflictPreview(latest)
  }

  function useServerVersion() {
    if (!conflictPreview) return
    applyServerDocument(conflictPreview)
    save.setConflictOpen(false)
    setConflictPreview(null)
    onNoticeRef.current('已切换到服务器版本。')
  }

  /**
   * 生成任务完成后刷新正文：有未保存修改时保留草稿、不覆盖编辑器。
   * 返回结果由调用方决定提示口径（上传批次与后台生成任务的文案不同）。
   */
  const refreshIfNewer = useCallback(async (): Promise<'updated' | 'unchanged' | 'dirty' | 'failed'> => {
    if (save.isDirty()) return 'dirty'
    try {
      const latest = await notebookApi.getDocument()
      if (!pageActiveRef.current) return 'failed'
      if (save.isDirty()) return 'dirty'
      if (latest.revision <= save.revision) return 'unchanged'
      applyServerDocument(latest)
      return 'updated'
    } catch {
      return 'failed'
    }
  }, [applyServerDocument, notebookApi, save.isDirty, save.revision])

  const dirty = save.state !== 'saved' || title !== (outline?.title ?? '')

  return {
    outline, setOutline, title, setTitle, content, setContent, loaded, editorReady, setEditorReady,
    loadError, documentWarning, titleError, setTitleError, titleSaving, lastTitleSavedAt,
    draftFound, setDraftFound, conflictPreview, setConflictPreview, editVersion, setEditVersion,
    save, dirty, editorReadyRef, pageActiveRef,
    handleChange, insertAI, adoptDocument, renameTitle, reloadOutline, applyServerDocument,
    refreshNotebookAfterUpload, refreshIfNewer, restoreDraft, discardDraft, showServerVersion, useServerVersion,
  }
}
