import { useState } from 'react'

import { DiffView } from './DiffView'
import { applySelected, diffRows, hunksOf } from './noteDiff'
import type { NotebookEditSuggestion } from '../../types'
import { docToMarkdown } from '../notebook-editor/document'

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
            <DiffView rows={rows} skipped={skipSet} onToggle={toggle} />
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
      <small className="agent-cards-title">🌿 旧版知识提议 · 不会写入 Notebook 正文或当前知识森林</small>
      {suggestions.map((proposal) => (
        <article key={proposal.id} className="agent-card agent-card-info" role="listitem">
          <p className="agent-card-body">提议新增知识点「{proposal.name}」。该提议仅保留在历史记录中；当前知识结构由 Notebook 正文生成。</p>
        </article>
      ))}
    </div>
  )
}

export function NotebookEditSuggestionCards({ suggestions, busyId, onReview }: {
  suggestions: NotebookEditSuggestion[]
  busyId?: string
  onReview: (suggestion: NotebookEditSuggestion, decision: 'accept' | 'reject', selectedIndices?: number[]) => void
}) {
  const [selected, setSelected] = useState<Record<string, Set<number>>>({})
  if (!suggestions.length) return null
  return <div className="agent-cards" role="list" aria-label="待审核的 Notebook 修改建议">
    <small className="agent-cards-title">📝 Notebook 修改建议 · 选择要应用的结构化操作，确认后写入</small>
    {suggestions.map((item) => {
      const selectedIndices = selected[item.id] ?? new Set(item.operations.map((_, index) => index))
      return <article key={item.id} className="agent-card" role="listitem">
        <p className="agent-card-body">《{item.notebook_title ?? 'Notebook'}》· {item.rationale || 'AI 提出的修改建议'}</p>
        <fieldset className="notebook-edit-operations">
          <legend>修改操作</legend>
          {item.operations.map((operation, index) => <label key={`${index}-${operation.op}`}>
            <input type="checkbox" checked={selectedIndices.has(index)} onChange={() => setSelected((current) => {
              const next = new Set(current[item.id] ?? item.operations.map((_, i) => i))
              next.has(index) ? next.delete(index) : next.add(index)
              return { ...current, [item.id]: next }
            })} />
            <span>{operation.op} · {operation.anchor || '文末'}{operation.content ? `：${operation.content}` : ''}</span>
          </label>)}
        </fieldset>
        {item.proposed_content ? <details className="notebook-edit-preview">
          <summary>查看完整建议正文（预览）</summary>
          <pre>{docToMarkdown(item.proposed_content)}</pre>
        </details> : null}
        <div className="agent-card-actions">
          <button type="button" className="agent-card-confirm" disabled={busyId === item.id || selectedIndices.size === 0}
            onClick={() => onReview(item, 'accept', [...selectedIndices].sort((a, b) => a - b))}>
            {busyId === item.id ? '写入中…' : `采纳所选操作（${selectedIndices.size}/${item.operations.length}）`}
          </button>
          <button type="button" className="agent-card-reject" disabled={busyId === item.id}
            onClick={() => onReview(item, 'reject')}>忽略</button>
        </div>
      </article>
    })}
  </div>
}
