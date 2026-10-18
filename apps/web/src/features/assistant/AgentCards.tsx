import type { AgentSuggestion } from '../../api/agent'

/**
 * agent 产生的待确认项卡片：
 * - ``NoteSuggestionCards``：笔记修改建议，带 采纳/忽略 按钮（走现有建议-确认接口）；
 * - ``KnowledgeProposalCards``：知识节点提议是信息卡，审核入口在知识图谱页（那里有自己的审核流）。
 */

export type PendingNoteSuggestion = {
  id: string
  note_id: string
  proposed_markdown: string
  impact: string
  status: string
}

export function NoteSuggestionCards({
  suggestions,
  busyId,
  onReview,
}: {
  suggestions: PendingNoteSuggestion[]
  busyId?: string
  onReview: (suggestion: PendingNoteSuggestion, decision: 'confirm' | 'reject') => void
}) {
  if (suggestions.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="待确认的笔记修改建议">
      <small className="agent-cards-title">📝 笔记修改建议 · 确认后才会写入</small>
      {suggestions.map((suggestion) => (
        <article key={suggestion.id} className="agent-card" role="listitem">
          <p className="agent-card-body">{suggestion.impact || 'AI 提出的修改建议'}</p>
          <details className="agent-card-preview">
            <summary>查看建议全文</summary>
            <pre>{suggestion.proposed_markdown}</pre>
          </details>
          <div className="agent-card-actions">
            <button
              type="button"
              className="agent-card-confirm"
              disabled={busyId === suggestion.id}
              onClick={() => onReview(suggestion, 'confirm')}
            >{busyId === suggestion.id ? '处理中…' : '采纳'}</button>
            <button
              type="button"
              className="agent-card-reject"
              disabled={busyId === suggestion.id}
              onClick={() => onReview(suggestion, 'reject')}
            >忽略</button>
          </div>
        </article>
      ))}
    </div>
  )
}

export function KnowledgeProposalCards({ suggestions }: { suggestions: Extract<AgentSuggestion, { type: 'knowledge_proposal' }>[] }) {
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
