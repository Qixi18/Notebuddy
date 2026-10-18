import { useState } from 'react'

import { DiffView } from './DiffView'
import { applySelected, diffRows, hunksOf } from './noteDiff'

export type InlineSuggestion = {
  id: string
  proposed_markdown: string
  impact: string
  status: string
}

/** 把待确认的 AI 修改建议原位渲染进笔记正文：红删绿增嵌在原文位置，
 * 每处变更可独立勾选，「采纳所选项」只写入勾选部分（部分采纳）。 */
export function NoteSuggestionsInline({ content, suggestions, busyId, onReview }: {
  content: string
  suggestions: InlineSuggestion[]
  busyId?: string
  onReview: (suggestion: InlineSuggestion, decision: 'confirm' | 'reject', finalMarkdown?: string) => void
}) {
  const [skipped, setSkipped] = useState<Record<string, Set<string>>>({})
  const suggestion = suggestions[0]
  if (!suggestion) return null

  const rows = diffRows(content, suggestion.proposed_markdown)
  const hunks = hunksOf(rows)
  const skipSet = skipped[suggestion.id] ?? new Set<string>()
  const selectedKeys = new Set(hunks.filter((hunk) => !skipSet.has(hunk.key)).map((hunk) => hunk.key))
  const finalText = applySelected(rows, selectedKeys)
  const partial = finalText !== suggestion.proposed_markdown
  const toggle = (key: string) => {
    setSkipped((current) => {
      const next = new Set(current[suggestion.id] ?? [])
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return { ...current, [suggestion.id]: next }
    })
  }

  return (
    <div className="note-inline-suggestions">
      <p className="note-inline-banner" role="status">
        📝 AI 修改建议{suggestions.length > 1 ? `（共 ${suggestions.length} 条，正在展示第 1 条）` : ''}：
        {suggestion.impact || '请在下方逐块勾选后采纳'}——<strong>红 = 删除，绿 = 新增</strong>，勾选后点「采纳所选项」直接写入原文。
      </p>
      <DiffView rows={rows} skipped={skipSet} onToggle={toggle} />
      <div className="note-inline-actions">
        <button
          type="button"
          className="primary-button"
          disabled={busyId === suggestion.id}
          onClick={() => onReview(suggestion, 'confirm', finalText)}
        >{busyId === suggestion.id ? '写入中…' : partial ? `采纳所选项（${selectedKeys.size}/${hunks.length} 块）` : '采纳进原文'}</button>
        <button
          type="button"
          className="secondary-button"
          disabled={busyId === suggestion.id}
          onClick={() => onReview(suggestion, 'reject')}
        >忽略此建议</button>
        {suggestions.length > 1 ? <small>采纳或忽略后，下一条建议会接着展示。</small> : null}
      </div>
    </div>
  )
}
