import { useState, type ReactNode } from 'react'

import { applySelected, diffRows, hunksOf } from './noteDiff'

/**
 * agent 产生的待确认项卡片：
 * - ``NoteSuggestionCards``：笔记修改建议——红删绿增的逐块 diff 视图，
 *   每块可独立勾选，「采纳所选项」只应用勾选块（部分采纳）；
 *   采纳后卡片保留「撤销本次 AI 改动」（回写采纳前正文）。
 * - ``KnowledgeProposalCards``：知识节点提议是信息卡，审核入口在知识图谱页。
 */

export type PendingNoteSuggestion = {
  id: string
  note_id: string
  proposed_markdown: string
  impact: string
  status: string
  note_title?: string
}

export function NoteSuggestionCards({
  suggestions,
  currentContent,
  busyId,
  adoptedContents,
  onReview,
  onUndo,
}: {
  suggestions: PendingNoteSuggestion[]
  currentContent: string
  busyId?: string
  /** 已采纳建议 id → 采纳前正文（撤销时回写） */
  adoptedContents: Record<string, string>
  onReview: (suggestion: PendingNoteSuggestion, decision: 'confirm' | 'reject', finalMarkdown?: string) => void
  onUndo: (suggestion: PendingNoteSuggestion) => void
}) {
  const [skipped, setSkipped] = useState<Record<string, Set<string>>>({})

  if (suggestions.length === 0) return null

  return (
    <div className="agent-cards" role="list" aria-label="待确认的笔记修改建议">
      <small className="agent-cards-title">📝 笔记修改建议 · 勾选要应用的变更块，确认后才会写入</small>
      {suggestions.map((suggestion) => {
        const adopted = adoptedContents[suggestion.id] !== undefined
        if (adopted) {
          return (
            <article key={suggestion.id} className="agent-card agent-card-adopted" role="listitem">
              <p className="agent-card-body">已采纳本次修改，《{suggestion.note_title ?? '当前笔记'}》已更新。</p>
              <div className="agent-card-actions">
                <button
                  type="button"
                  className="agent-card-reject"
                  disabled={busyId === suggestion.id}
                  onClick={() => onUndo(suggestion)}
                >{busyId === suggestion.id ? '撤销中…' : '撤销本次 AI 改动'}</button>
              </div>
            </article>
          )
        }
        const rows = diffRows(currentContent, suggestion.proposed_markdown)
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
          <article key={suggestion.id} className="agent-card" role="listitem">
            <p className="agent-card-body">{suggestion.impact || 'AI 提出的修改建议'}</p>
            <div className="agent-diff">
              {rows.map((row, index) => {
                const elements: ReactNode[] = []
                const hunkKey = row.hunk
                const hunkStarts = hunkKey !== undefined && rows[index - 1]?.hunk !== hunkKey
                if (hunkStarts) {
                  elements.push(
                    <label key={`${hunkKey}-head`} className="agent-diff-hunk-head">
                      <input
                        type="checkbox"
                        checked={!skipSet.has(hunkKey)}
                        onChange={() => toggle(hunkKey)}
                      />
                      变更块 {hunkKey.slice(1)}
                    </label>,
                  )
                }
                elements.push(
                  <div
                    key={`${hunkKey ?? 'same'}-${index}`}
                    className={`agent-diff-row agent-diff-${row.type}`}
                  >{row.text || ' '}</div>,
                )
                return elements
              })}
            </div>
            <div className="agent-card-actions">
              <button
                type="button"
                className="agent-card-confirm"
                disabled={busyId === suggestion.id}
                onClick={() => onReview(suggestion, 'confirm', finalText)}
              >{busyId === suggestion.id ? '写入中…' : partial ? `采纳所选项（${selectedKeys.size}/${hunks.length} 块）` : '采纳'}</button>
              <button
                type="button"
                className="agent-card-reject"
                disabled={busyId === suggestion.id}
                onClick={() => onReview(suggestion, 'reject')}
              >忽略</button>
            </div>
          </article>
        )
      })}
    </div>
  )
}

export function KnowledgeProposalCards({ suggestions }: { suggestions: Array<{ type: 'knowledge_proposal'; id: string; name: string }> }) {
  if (suggestions.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="知识节点提议">
      <small className="agent-cards-title">🌿 知识节点提议 · 到课程知识图谱审核后才会进入图谱</small>
      {suggestions.map((proposal) => (
        <article key={proposal.id} className="agent-card agent-card-info" role="listitem">
          <p className="agent-card-body">提议新增知识点「{proposal.name}」</p>
        </article>
      ))}
    </div>
  )
}
