import { useCallback, useEffect, useState } from 'react'

import { api, ApiError } from '../../api'
import type { DocNode, NotebookEditSuggestion } from '../../types'

export type NotebookSuggestionTarget = {
  courseId: string
  notebookId: string
  title: string
  revision: number
  editVersion?: number
  isDirty?: () => boolean
  adoptDocument?: (content: DocNode, revision: number,
    updatedAt: string, expectedEditVersion: number) => boolean
}

/** Notebook suggestion lifecycle shared by the full page and the assistant dock. */
export function useNotebookEditSuggestions({ target, courseId, agentFinalId }: {
  target?: NotebookSuggestionTarget | null
  /** When no Notebook is locked, show pending suggestions across this course. */
  courseId?: string
  agentFinalId?: string
}) {
  const [suggestions, setSuggestions] = useState<NotebookEditSuggestion[]>([])
  const [busyId, setBusyId] = useState<string>()
  const [notice, setNotice] = useState<string>()

  const reload = useCallback(async () => {
    if (!target?.notebookId && !courseId) { setSuggestions([]); return }
    try {
      const rows = target?.notebookId
        ? (await api.listNotebookEditSuggestions(target.notebookId)).map((item) => ({ ...item, notebook_title: target.title }))
        : await api.listCourseNotebookEditSuggestions(courseId!)
      setSuggestions(rows)
    } catch {
      setSuggestions([])
    }
  }, [courseId, target?.notebookId, target?.title])

  useEffect(() => { void reload() }, [agentFinalId, reload])

  const review = useCallback(async (
    suggestion: NotebookEditSuggestion,
    decision: 'accept' | 'reject',
    selectedOperationIndices?: number[],
  ) => {
    const lockedTarget = target?.notebookId === suggestion.notebook_id ? target : null
    if (!lockedTarget && !courseId) return
    if (decision === 'accept' && lockedTarget?.isDirty?.()) {
      setNotice('当前笔记有未保存修改。请先保存正文，再确认这条建议。')
      return
    }
    if (decision === 'accept' && lockedTarget && lockedTarget.revision !== suggestion.base_revision) {
      setNotice('正文版本已变化，请刷新后重新生成建议。')
      return
    }
    setBusyId(suggestion.id)
    setNotice(undefined)
    const editVersion = target?.editVersion ?? 0
    try {
      const result = await api.reviewNotebookEditSuggestion(
        suggestion.notebook_id, suggestion.id, decision,
        lockedTarget?.revision ?? suggestion.base_revision,
        decision === 'accept' ? selectedOperationIndices : undefined,
      )
      if (decision === 'accept') {
        const adopted = result.content
          ? lockedTarget?.adoptDocument?.(result.content, result.revision, result.updated_at, editVersion)
          : false
        setNotice(lockedTarget && adopted === false
          ? '修改已写入服务端；编辑期间正文发生变化，请刷新后核对。'
          : `已将建议写入《${suggestion.notebook_title ?? lockedTarget?.title ?? 'Notebook'}》，并生成新的正文修订。`)
      } else setNotice('已忽略这条修改建议。')
      await reload()
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '正文或建议版本已变化，请刷新后重新确认。'
        : cause instanceof Error ? cause.message : '处理修改建议失败')
    } finally {
      setBusyId(undefined)
    }
  }, [courseId, reload, target])

  const applyAll = useCallback(async () => {
    const activeCourseId = target?.courseId ?? courseId
    if (!activeCourseId || suggestions.length === 0) return
    if (target?.isDirty?.()) {
      setNotice('当前笔记有未保存修改。请先保存正文，再确认这些建议。')
      return
    }
    setBusyId('__all__')
    setNotice(undefined)
    const editVersion = target?.editVersion ?? 0
    try {
      const result = await api.applyAllCourseNotebookEditSuggestions(
        activeCourseId, suggestions.map((suggestion) => suggestion.id),
      )
      let editorOutOfDate = false
      let editorRefreshFailed = false
      if (target && result.notebooks.some((item) => item.notebook_id === target.notebookId)) {
        try {
          const document = await api.getNotebookDocument(target.courseId, target.notebookId)
          editorOutOfDate = target.adoptDocument?.(
            document.content, document.revision, document.updated_at, editVersion,
          ) === false
        } catch {
          editorRefreshFailed = true
        }
      }
      await reload()
      setNotice(editorRefreshFailed
        ? `已将 ${result.updated} 条建议写入 ${result.notebooks.length} 篇 Notebook；当前编辑器未能自动刷新，请重新打开目标笔记核对。`
        : editorOutOfDate
        ? `已将 ${result.updated} 条建议写入 ${result.notebooks.length} 篇 Notebook；当前编辑器期间正文发生变化，请刷新并核对服务端版本。`
        : `已将 ${result.updated} 条建议写入 ${result.notebooks.length} 篇 Notebook。`)
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '部分笔记正文或建议状态已变化，请刷新列表后重新审核。'
        : cause instanceof Error ? cause.message : '批量写入建议失败')
      await reload()
    } finally {
      setBusyId(undefined)
    }
  }, [courseId, reload, suggestions, target])

  const changes = [...suggestions].sort((left, right) =>
    left.notebook_id.localeCompare(right.notebook_id) || left.created_at.localeCompare(right.created_at),
  ).map((suggestion) => ({
    id: suggestion.id,
    noteId: suggestion.notebook_id,
    noteTitle: suggestion.notebook_title ?? 'Notebook',
    chapter: '结构化修改建议',
    added: suggestion.operations.filter((operation) => operation.op !== 'remove_section').length,
    removed: suggestion.operations.filter((operation) => operation.op === 'remove_section').length,
    status: 'pending' as const,
  }))

  return { suggestions, busyId, notice, review, reload, applyAll, changes }
}
