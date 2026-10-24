import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, ApiError } from '../../api'
import type { Note } from '../../types'
import type { PendingNoteSuggestion } from './AgentCards'
import { applySelected, diffRows, hunksOf } from './noteDiff'

/**
 * agent 产出的「笔记修改建议」多目标状态机（P4）：按 note_id 管理课程内多篇笔记的建议。
 *
 * 两条入口共用：
 * - 答疑页传 courseId → 走课程级 pending 端点，目标集合 = 本课程全部待确认建议
 *   （语义是「本课程的待确认改动」，不承诺只属于本会话）；
 * - 悬浮坞不传 courseId → 逐目标 listSuggestions，行为与旧单目标版一致（不传发现开关）。
 *
 * 数据安全红线：每条建议的 diff 基准、写入、撤销都必须用 **它自己那篇笔记** 的
 * 正文与 revision（notesById 缓存），绝不能拿别的笔记的正文当基准——多目标下沿用
 * 单一正文会把 A 的内容写进 B。
 */
export function useNoteSuggestions({ targets, knownNotes, courseId, refreshNotes, agentFinalId }: {
  /** 显式目标笔记 id（悬浮坞 = 当前打开的笔记；答疑页传空数组，目标来自课程级建议列表） */
  targets: string[]
  /** 已知笔记（工作区笔记 / 当前打开的笔记）作为正文与 revision 缓存种子 */
  knownNotes: Note[]
  /** 传了就走课程级 pending 端点（答疑页模式） */
  courseId?: string
  /** 写回后刷新工作区笔记列表 */
  refreshNotes: () => Promise<void>
  /** agent 每次 final 都会换新 id → 用来触发「又产出建议了」的重新拉取 */
  agentFinalId?: string
}) {
  const [suggestions, setSuggestions] = useState<PendingNoteSuggestion[]>([])
  /** 目标笔记缓存：id → 完整 Note（diff 基准 + 写入/撤销用的 revision_number） */
  const [notesById, setNotesById] = useState<Record<string, Note>>({})
  /** 已采纳的建议 id → 采纳前的正文（撤销时回写） */
  const [adopted, setAdopted] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string>()
  const [notice, setNotice] = useState<string>()

  const knownNotesRef = useRef(knownNotes)
  knownNotesRef.current = knownNotes
  /* 写入路径（review/undo/applyAll）读缓存用 ref：回调闭包里始终拿到最新一版 */
  const notesByIdRef = useRef(notesById)
  notesByIdRef.current = notesById
  /* review 返回的 Note 必须字段完整才入缓存：部分响应（缺 revision/正文）会破坏撤销与后续 diff 基准 */
  const mergeNoteResponse = useCallback((noteId: string, updated: Note | undefined) => {
    if (!updated || typeof updated.revision_number !== 'number' || typeof updated.content_markdown !== 'string') return
    setNotesById((current) => (current[noteId] === updated ? current : { ...current, [noteId]: updated }))
  }, [])
  /* 用 id:revision 签名做依赖：工作区刷新后 revision 变化会更新缓存，数组引用变化不会引发多余合并 */
  const notesSignature = knownNotes.map((note) => `${note.id}:${note.revision_number}`).join('|')
  useEffect(() => {
    setNotesById((current) => {
      let changed = false
      const next = { ...current }
      for (const note of knownNotesRef.current) {
        if (note && next[note.id] !== note) { next[note.id] = note; changed = true }
      }
      return changed ? next : current
    })
  }, [notesSignature])

  const targetKey = targets.join(',')
  useEffect(() => {
    let alive = true
    if (courseId) {
      void api.listCourseSuggestions(courseId)
        .then((items) => {
          if (!alive) return
          setSuggestions(items.filter((item) => item.status === 'pending') as PendingNoteSuggestion[])
        })
        .catch(() => { if (alive) setSuggestions([]) })
      return () => { alive = false }
    }
    /* 坞模式：逐目标拉取（现状只有一篇），保持旧行为 */
    const ids = targetKey ? targetKey.split(',') : []
    void Promise.all(ids.map((id) => api.listSuggestions(id).catch(() => [])))
      .then((groups) => {
        if (!alive) return
        setSuggestions(groups.flat().filter((item) => item.status === 'pending') as PendingNoteSuggestion[])
      })
    return () => { alive = false }
  }, [courseId, agentFinalId, targetKey])

  /* 正文缓存补齐：建议涉及的目标笔记，既不在 knownNotes 也不在缓存里的才逐个拉取。
     拉不到的笔记在 diff/写入处按「正文缺失」跳过——绝不允许拿别的笔记正文顶替。 */
  const neededKey = useMemo(() => {
    const cached = new Set<string>(knownNotes.map((note) => note.id))
    for (const id of Object.keys(notesById)) cached.add(id)
    const ids = new Set<string>(targets)
    for (const item of suggestions) ids.add(item.note_id)
    return [...ids].filter((id) => !cached.has(id)).sort().join(',')
  }, [suggestions, targets, knownNotes, notesById])
  useEffect(() => {
    if (!neededKey) return
    let alive = true
    void Promise.all(neededKey.split(',').map((id) => api.getNote(id).catch(() => null)))
      .then((fetched) => {
        if (!alive) return
        setNotesById((current) => {
          const next = { ...current }
          for (const note of fetched) if (note) next[note.id] = note
          return next
        })
      })
    return () => { alive = false }
  }, [neededKey])

  /** 采纳（可带逐块勾选后的最终正文）或忽略 */
  const review = useCallback(async (suggestion: PendingNoteSuggestion, decision: 'confirm' | 'reject', finalMarkdown?: string) => {
    setBusyId(suggestion.id)
    setNotice(undefined)
    const targetNote = notesByIdRef.current[suggestion.note_id]
    const beforeContent = targetNote?.content_markdown ?? ''
    const title = targetNote?.title ?? suggestion.note_title ?? '笔记'
    try {
      const updated = await api.reviewSuggestion(suggestion.note_id, suggestion.id, decision, undefined, finalMarkdown)
      if (decision === 'confirm') {
        /* review 返回写后的最新 Note（含新 revision）：直接入缓存，撤销/后续采纳都用它 */
        mergeNoteResponse(suggestion.note_id, updated)
        setAdopted((current) => ({ ...current, [suggestion.id]: beforeContent }))
        await refreshNotes()
        const partial = finalMarkdown !== undefined && finalMarkdown !== suggestion.proposed_markdown
        setNotice(`已${partial ? '部分采纳' : '采纳'}建议，《${title}》已更新，可在修订历史中回退。`)
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
  }, [mergeNoteResponse, refreshNotes])

  /** 撤销本次 AI 改动：回写采纳前正文（用目标笔记**当前** revision） */
  const undo = useCallback(async (suggestion: PendingNoteSuggestion) => {
    const targetNote = notesByIdRef.current[suggestion.note_id]
    const beforeContent = adopted[suggestion.id]
    const title = targetNote?.title ?? suggestion.note_title ?? '笔记'
    if (!targetNote || beforeContent === undefined) {
      setNotice('找不到这篇笔记的当前内容，请刷新页面后再撤销。')
      return
    }
    setBusyId(suggestion.id)
    setNotice(undefined)
    try {
      await api.updateNote(suggestion.note_id, beforeContent, targetNote.revision_number)
      await refreshNotes()
      setAdopted((current) => {
        const next = { ...current }
        delete next[suggestion.id]
        return next
      })
      setSuggestions((current) => current.filter((item) => item.id !== suggestion.id))
      setNotice(`已撤销本次 AI 改动，《${title}》恢复到采纳前内容。`)
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '笔记刚在别处更新过，请刷新笔记后再撤销。'
        : cause instanceof Error ? cause.message : '撤销失败')
    } finally {
      setBusyId(undefined)
    }
  }, [adopted, refreshNotes])

  /**
   * 全部写入：**按 note_id 分组**，每组以该篇当前正文为基准逐条累加，组间互不影响。
   * 每次 review(confirm) 服务端都按笔记当前 revision 写入并返回最新 Note，
   * 循环结束即落库完毕——不能再补 updateNote（旧 revision 提交必然 409）。
   * 正文缓存缺失的组直接跳过并提示（数据安全红线：不用别的笔记正文当基准）。
   */
  const applyAll = useCallback(async () => {
    if (suggestions.length === 0) return
    setBusyId('__all__')
    setNotice(undefined)
    const groups = new Map<string, PendingNoteSuggestion[]>()
    for (const suggestion of suggestions) {
      const group = groups.get(suggestion.note_id) ?? []
      group.push(suggestion)
      groups.set(suggestion.note_id, group)
    }
    /** 每条写入建议对应的「采纳前正文」＝该组第一笔写入前的那篇正文（撤销回写用） */
    const written: Array<{ id: string; before: string }> = []
    const writtenNoteIds = new Set<string>()
    const skippedTitles: string[] = []
    try {
      for (const [noteId, group] of groups) {
        const baseNote = notesByIdRef.current[noteId]
        if (!baseNote) {
          skippedTitles.push(group[0]?.note_title ?? '一篇笔记')
          continue
        }
        const before = baseNote.content_markdown
        let content = before
        for (const suggestion of group) {
          const rows = diffRows(content, suggestion.proposed_markdown)
          const hunks = hunksOf(rows)
          content = applySelected(rows, new Set(hunks.map((hunk) => hunk.key)))
          const updated = await api.reviewSuggestion(noteId, suggestion.id, 'confirm', undefined, content)
          mergeNoteResponse(noteId, updated)
          written.push({ id: suggestion.id, before })
        }
        writtenNoteIds.add(noteId)
      }
      await refreshNotes()
      setAdopted((current) => {
        const next = { ...current }
        for (const entry of written) next[entry.id] = entry.before
        return next
      })
      setSuggestions((current) => current.filter((item) => !writtenNoteIds.has(item.note_id)))
      setNotice(`已把 ${written.length} 条建议写入${skippedTitles.length ? `；${skippedTitles.join('、')}的正文未能获取，已跳过` : ''}。`)
    } catch (cause) {
      setNotice(cause instanceof ApiError && cause.status === 409
        ? '笔记刚在别处更新过，请刷新笔记后再写入。'
        : cause instanceof Error ? cause.message : '写入失败')
    } finally {
      setBusyId(undefined)
    }
  }, [mergeNoteResponse, suggestions, refreshNotes])

  /** 供改动栏用的摘要：每条建议的新增/删除行数与预览（diff 基准 = 该建议自己的笔记正文） */
  const changes = useMemo(() => {
    return suggestions.map((suggestion) => {
      const targetNote = notesById[suggestion.note_id]
      const current = targetNote?.content_markdown ?? ''
      const rows = diffRows(current, suggestion.proposed_markdown)
      const added = rows.filter((row) => row.type === 'added')
      const removed = rows.filter((row) => row.type === 'removed')
      /* 应用这条建议后的整篇正文（预览「改后」用） */
      const proposed = applySelected(rows, new Set(hunksOf(rows).map((hunk) => hunk.key)))
      return {
        id: suggestion.id,
        noteId: suggestion.note_id,
        noteTitle: targetNote?.title ?? suggestion.note_title ?? '笔记',
        chapter: targetNote?.section_key ?? null,
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
  }, [suggestions, notesById])

  /** 建议卡用的「当前正文」映射：每条建议按自己的 note_id 取基准（数据安全红线） */
  const contentById = useMemo(() => {
    const map: Record<string, string> = {}
    for (const [id, note] of Object.entries(notesById)) map[id] = note.content_markdown ?? ''
    return map
  }, [notesById])

  return { suggestions, adopted, busyId, notice, contentById, notesById, review, undo, applyAll, changes }
}
