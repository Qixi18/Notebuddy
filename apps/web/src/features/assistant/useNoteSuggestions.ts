import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, ApiError } from '../../api'
import type { Note } from '../../types'
import type { PendingNoteSuggestion } from './AgentCards'
import { applySelected, diffRows, hunksOf } from './noteDiff'

/**
 * agent 产出的「笔记修改建议」状态机：拉取待确认项、采纳/忽略、撤销本次改动。
 * 悬浮坞与答疑页共用这一份，避免两条入口的写入逻辑漂移。
 *
 * 建议挂在**目标笔记**上：悬浮坞锁「当前打开的笔记」，答疑页锁「用户选定的那篇」，
 * 所以这里只认传入的 noteId / note，不关心笔记是从哪儿来的。
 */
export function useNoteSuggestions({ noteId, note, refreshNotes, agentFinalId }: {
  /** 目标笔记 id；没有就不启用 */
  noteId?: string
  /** 目标笔记本体：diff 的当前正文 + 回写时的 revision_number */
  note?: Note
  /** 写回后刷新工作区笔记列表 */
  refreshNotes: () => Promise<void>
  /** agent 每次 final 都会换新 id → 用来触发「又产出建议了」的重新拉取 */
  agentFinalId?: string
}) {
  const [suggestions, setSuggestions] = useState<PendingNoteSuggestion[]>([])
  /** 已采纳的建议 id → 采纳前的正文（撤销时回写） */
  const [adopted, setAdopted] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string>()
  const [notice, setNotice] = useState<string>()

  useEffect(() => {
    if (!noteId) { setSuggestions([]); return }
    let alive = true
    void api.listSuggestions(noteId)
      .then((items) => {
        if (!alive) return
        /* 后端返回的建议不一定带 note_title，补上目标笔记名，卡片与改动栏才显示得出来 */
        const pending = items.filter((item) => item.status === 'pending') as PendingNoteSuggestion[]
        setSuggestions(pending.map((item) => ({ ...item, note_title: item.note_title ?? note?.title })))
      })
      .catch(() => { if (alive) setSuggestions([]) })
    return () => { alive = false }
  }, [noteId, agentFinalId, note?.title])

  /** 采纳（可带逐块勾选后的最终正文）或忽略 */
  const review = useCallback(async (suggestion: PendingNoteSuggestion, decision: 'confirm' | 'reject', finalMarkdown?: string) => {
    setBusyId(suggestion.id)
    setNotice(undefined)
    const beforeContent = note?.content_markdown ?? ''
    try {
      await api.reviewSuggestion(suggestion.note_id, suggestion.id, decision, undefined, finalMarkdown)
      if (decision === 'confirm') {
        setAdopted((current) => ({ ...current, [suggestion.id]: beforeContent }))
        await refreshNotes()
        const partial = finalMarkdown !== undefined && finalMarkdown !== suggestion.proposed_markdown
        setNotice(`已${partial ? '部分采纳' : '采纳'}建议，《${note?.title ?? '笔记'}》已更新，可在修订历史中回退。`)
      } else {
        setSuggestions((current) => current.filter((item) => item.id !== suggestion.id))
        setNotice('已忽略该建议。')
      }
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '这条建议已处理或笔记刚更新过。'
        : cause instanceof Error ? cause.message : '处理建议失败')
    } finally {
      setBusyId(undefined)
    }
  }, [note, refreshNotes])

  /** 撤销本次 AI 改动：回写采纳前正文 */
  const undo = useCallback(async (suggestion: PendingNoteSuggestion) => {
    const beforeContent = adopted[suggestion.id]
    if (!note || beforeContent === undefined) return
    setBusyId(suggestion.id)
    setNotice(undefined)
    try {
      await api.updateNote(suggestion.note_id, beforeContent, note.revision_number)
      await refreshNotes()
      setAdopted((current) => {
        const next = { ...current }
        delete next[suggestion.id]
        return next
      })
      setSuggestions((current) => current.filter((item) => item.id !== suggestion.id))
      setNotice(`已撤销本次 AI 改动，《${note.title}》恢复到采纳前内容。`)
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '笔记刚在别处更新过，请刷新笔记后再撤销。'
        : cause instanceof Error ? cause.message : '撤销失败')
    } finally {
      setBusyId(undefined)
    }
  }, [adopted, note, refreshNotes])

  /**
   * 全部写入：把待确认的建议按顺序累加进正文。
   * 每条建议的 proposed_markdown 都是「整篇改写版」，所以必须逐条以**当前累计结果**为基准重算 diff，
   * 否则后一条会覆盖前一条的改动。
   */
  const applyAll = useCallback(async () => {
    if (!note || suggestions.length === 0) return
    setBusyId('__all__')
    setNotice(undefined)
    const before = note.content_markdown
    try {
      let content = before
      for (const suggestion of suggestions) {
        const rows = diffRows(content, suggestion.proposed_markdown)
        const hunks = hunksOf(rows)
        content = applySelected(rows, new Set(hunks.map((hunk) => hunk.key)))
        await api.reviewSuggestion(suggestion.note_id, suggestion.id, 'confirm', undefined, content)
      }
      await api.updateNote(note.id, content, note.revision_number)
      await refreshNotes()
      setAdopted((current) => {
        const next = { ...current }
        for (const suggestion of suggestions) next[suggestion.id] = before
        return next
      })
      setSuggestions([])
      setNotice(`已把 ${suggestions.length} 条建议写入《${note.title}》。`)
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '笔记刚在别处更新过，请刷新笔记后再写入。'
        : cause instanceof Error ? cause.message : '写入失败')
    } finally {
      setBusyId(undefined)
    }
  }, [note, suggestions, refreshNotes])

  /** 供「本次改动」栏用的摘要：每条建议的新增/删除行数与预览 */  const changes = useMemo(() => {
    const current = note?.content_markdown ?? ''
    return suggestions.map((suggestion) => {
      const rows = diffRows(current, suggestion.proposed_markdown)
      const added = rows.filter((row) => row.type === 'added')
      const removed = rows.filter((row) => row.type === 'removed')
      /* 应用这条建议后的整篇正文（预览「改后」用） */
      const proposed = applySelected(rows, new Set(hunksOf(rows).map((hunk) => hunk.key)))
      return {
        id: suggestion.id,
        noteId: suggestion.note_id,
        noteTitle: suggestion.note_title ?? note?.title ?? '笔记',
        chapter: note?.section_key ?? null,
        added: added.length,
        removed: removed.length,
        status: 'pending' as const,
        preview: {
          added: added[0]?.text,
          removed: removed[0]?.text,
          context: suggestion.impact,
        },
        diff: rows,
        proposed,
        suggestion,
      }
    })
  }, [suggestions, note])

  return { suggestions, adopted, busyId, notice, review, undo, applyAll, changes }
}
