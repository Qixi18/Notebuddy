import { useEffect, useState } from 'react'

import { api } from '../../api'
import type { QuizDto } from '../../api/quiz'
import { DiffView } from './DiffView'
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
  currentContentByNoteId,
  busyId,
  adoptedContents,
  onReview,
  onUndo,
}: {
  suggestions: PendingNoteSuggestion[]
  /** 每篇笔记的当前正文：diff 基准按 suggestion.note_id 取，多目标下绝不共用单一正文 */
  currentContentByNoteId: Record<string, string>
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
        /* 数据安全红线：diff 基准必须是这条建议自己的那篇笔记 */
        const currentContent = currentContentByNoteId[suggestion.note_id] ?? ''
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
            <p className="agent-card-body">
              {suggestion.note_title && <small className="agent-card-note">《{suggestion.note_title}》</small>}
              {suggestion.impact || 'AI 提出的修改建议'}
            </p>
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
      <small className="agent-cards-title">🌿 知识节点提议 · 到课程知识图谱审核后才会进入图谱</small>
      {suggestions.map((proposal) => (
        <article key={proposal.id} className="agent-card agent-card-info" role="listitem">
          <p className="agent-card-body">提议新增知识点「{proposal.name}」</p>
        </article>
      ))}
    </div>
  )
}

/** QuizCards（v6 P10）：agent 出的自测卷——拉题目、作答、服务端判分讲评。 */
export function QuizCards({ quizzes, courseId }: {
  quizzes: Array<{ type: 'quiz'; id: string; quiz_id: string; title: string; item_count: number }>
  courseId?: string
}) {
  const [quizzesById, setQuizzesById] = useState<Record<string, QuizDto>>({})

  /* 一次拉课程内 active 卷子，按 id 匹配本批建议（答案不下发，判分在服务端） */
  useEffect(() => {
    if (!courseId || quizzes.length === 0) return
    let alive = true
    void api.listQuizzes(courseId, 'active')
      .then((items) => {
        if (!alive) return
        const map: Record<string, QuizDto> = {}
        for (const quiz of items) map[quiz.id] = quiz
        setQuizzesById(map)
      })
      .catch(() => { if (alive) setQuizzesById({}) })
    return () => { alive = false }
  }, [courseId, quizzes.length])

  if (quizzes.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="自测卷">
      <small className="agent-cards-title">📝 自测卷 · 作答后系统自动判分讲评（答案不出现在页面上）</small>
      {quizzes.map((quiz) => {
        const dto = quizzesById[quiz.quiz_id]
        if (!dto) {
          return (
            <article key={quiz.quiz_id} className="agent-card agent-card-info" role="listitem">
              <p className="agent-card-body">📄 {quiz.title}（{quiz.item_count} 题）{courseId ? '· 正在加载题目…' : ''}</p>
            </article>
          )
        }
        return <QuizCard key={quiz.quiz_id} quiz={dto} />
      })}
    </div>
  )
}

function QuizCard({ quiz }: { quiz: QuizDto }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [graded, setGraded] = useState<Record<string, { correct: boolean; answer: string; explanation: string; comment: string }>>({})
  const [busyId, setBusyId] = useState<string>()
  const [error, setError] = useState<string>()

  const gradedCount = Object.keys(graded).length
  const correctCount = Object.values(graded).filter((entry) => entry.correct).length
  const allGraded = gradedCount === quiz.items.length

  /* 点击即判（v6 用户反馈）：选择项一点就提交本题、立刻出对错；简答单独提交。
     答案与讲评在判分前不出现在页面上，判分后作为独立答案区与题目分离。 */
  function submitOne(item: QuizDto['items'][number], answer: string) {
    if (graded[item.id] || busyId || !answer.trim()) return
    setBusyId(item.id)
    setError(undefined)
    void api.submitAttempts(quiz.id, [{ item_id: item.id, answer }])
      .then((result) => {
        const verdict = result.results.find((entry) => entry.item_id === item.id)
        if (verdict) setGraded((current) => ({ ...current, [item.id]: verdict }))
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : '提交失败，请重试')
      })
      .finally(() => setBusyId(undefined))
  }

  return (
    <article className="agent-card quiz-paper" role="listitem">
      <header className="quiz-paper-head">
        <span className="quiz-paper-badge">自测卷</span>
        <strong className="quiz-paper-title">{quiz.title}</strong>
        <span className="quiz-paper-progress" role="status">
          {allGraded ? `得分 ${correctCount}/${quiz.items.length}` : `已判 ${gradedCount}/${quiz.items.length}`}
        </span>
      </header>
      {quiz.items.map((item) => {
        const verdict = graded[item.id]
        const picked = answers[item.id] ?? ''
        return (
          <section key={item.id} className={`quiz-item${verdict ? (verdict.correct ? ' is-correct' : ' is-wrong') : ''}`}>
            <p className="quiz-item-stem">
              <span className="quiz-item-no" aria-hidden="true">{item.seq}</span>
              {item.stem}
              {item.type === 'short' && <small>（简答）</small>}
            </p>
            {item.type === 'choice' ? (
              <div className="quiz-item-options" role="radiogroup" aria-label={`第 ${item.seq} 题选项`}>
                {item.options.map((option) => {
                  const isPicked = picked === option
                  const state = !verdict
                    ? isPicked ? ' is-selected' : ''
                    : option === verdict.answer ? ' is-correct' : isPicked ? ' is-wrong' : ' is-dim'
                  return (
                    <label key={option} className={`quiz-item-option${state}`}>
                      <input
                        type="radio"
                        name={`quiz-${quiz.id}-item-${item.id}`}
                        disabled={Boolean(verdict) || busyId === item.id}
                        checked={isPicked}
                        onChange={() => {
                          setAnswers((current) => ({ ...current, [item.id]: option }))
                          submitOne(item, option)
                        }}
                      />
                      <span>{option}</span>
                      {verdict && option === verdict.answer && <span className="quiz-option-mark" aria-hidden="true">✓</span>}
                      {verdict && isPicked && option !== verdict.answer && <span className="quiz-option-mark" aria-hidden="true">✗</span>}
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="quiz-item-short-wrap">
                <textarea
                  className="quiz-item-short"
                  value={picked}
                  disabled={Boolean(verdict)}
                  rows={3}
                  placeholder="写下你的回答…"
                  aria-label={`第 ${item.seq} 题作答`}
                  onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                />
                {!verdict && (
                  <button
                    type="button"
                    className="quiz-item-submit"
                    disabled={!picked.trim() || busyId === item.id}
                    onClick={() => submitOne(item, picked)}
                  >{busyId === item.id ? '判分中…' : '提交本题'}</button>
                )}
              </div>
            )}
            {/* 答案区：判分后才渲染，与题目区视觉分离 */}
            {verdict && (
              <div className={`quiz-verdict${verdict.correct ? ' is-correct' : ' is-wrong'}`}>
                <p className="quiz-verdict-line">
                  {verdict.correct ? '✓ 答对了' : '✗ 答错了'}
                  <span> · 你的回答：{picked || '（空）'}</span>
                  {!verdict.correct && verdict.answer && <span> · 正确答案：{verdict.answer}</span>}
                </p>
                {(verdict.explanation || verdict.comment) && (
                  <p className="quiz-verdict-why">{verdict.explanation}{verdict.comment}</p>
                )}
              </div>
            )}
          </section>
        )
      })}
      {allGraded && (
        <footer className="quiz-paper-foot">
          {correctCount === quiz.items.length ? '全对，漂亮！' : `错题已记录，之后可在复习里回看（${correctCount}/${quiz.items.length} 正确）。`}
        </footer>
      )}
      {error && <p className="workspace-agent-notice">{error}</p>}
    </article>
  )
}
