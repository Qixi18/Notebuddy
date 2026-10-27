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
export function useNotebookEditSuggestions({ target, agentFinalId }: {
  target?: NotebookSuggestionTarget | null
  agentFinalId?: string
}) {
  const [suggestions, setSuggestions] = useState<NotebookEditSuggestion[]>([])
  const [busyId, setBusyId] = useState<string>()
  const [notice, setNotice] = useState<string>()

  const reload = useCallback(async () => {
    if (!target?.notebookId) { setSuggestions([]); return }
    try {
      setSuggestions((await api.listNotebookEditSuggestions(target.notebookId)).map((item) => ({
        ...item, notebook_title: target.title,
      })))
    } catch {
      setSuggestions([])
    }
  }, [target?.notebookId, target?.title])

  useEffect(() => { void reload() }, [agentFinalId, reload])

  const review = useCallback(async (
    suggestion: NotebookEditSuggestion,
    decision: 'accept' | 'reject',
    selectedOperationIndices?: number[],
  ) => {
    if (!target || suggestion.notebook_id !== target.notebookId) return
    if (decision === 'accept' && target.isDirty?.()) {
      setNotice('当前笔记有未保存修改。请先保存正文，再确认这条建议。')
      return
    }
    if (decision === 'accept' && target.revision !== suggestion.base_revision) {
      setNotice('正文版本已变化，请刷新后重新生成建议。')
      return
    }
    setBusyId(suggestion.id)
    setNotice(undefined)
    const editVersion = target.editVersion ?? 0
    try {
      const result = await api.reviewNotebookEditSuggestion(
        target.notebookId, suggestion.id, decision, target.revision,
        decision === 'accept' ? selectedOperationIndices : undefined,
      )
      if (decision === 'accept') {
        const adopted = result.content
          ? target.adoptDocument?.(result.content, result.revision, result.updated_at, editVersion)
          : false
        setNotice(adopted === false
          ? '修改已写入服务端；编辑期间正文发生变化，请刷新后核对。'
          : `已将建议写入《${target.title}》，并生成新的正文修订。`)
      } else setNotice('已忽略这条修改建议。')
      await reload()
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '正文或建议版本已变化，请刷新后重新确认。'
        : cause instanceof Error ? cause.message : '处理修改建议失败')
    } finally {
      setBusyId(undefined)
    }
  }, [reload, target])

  return { suggestions, busyId, notice, review, reload }
}
