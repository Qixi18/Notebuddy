import { useEffect, useState } from 'react'

import { api } from '../../api'
import type { AgentSuggestion } from '../../api/agentStream'
import type { QuizDto } from '../../api/quiz'
import { readStorage, writeStorage } from '../../utils/safeStorage'
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

export type OutlineSuggestion = Extract<AgentSuggestion, { type: 'review_outline' }>
export type ContrastSuggestion = Extract<AgentSuggestion, { type: 'concept_contrast' }>

const OUTLINE_CHECKS_KEY = 'nb-outline-checks'

function loadOutlineChecks(): Record<string, boolean> {
  const raw = readStorage(OUTLINE_CHECKS_KEY)
  if (!raw) return {}
  try {
    return JSON.parse(raw) as Record<string, boolean>
  } catch {
    return {}
  }
}

const PRIORITY_LABELS: Record<OutlineSuggestion['modules'][number]['priority'], string> = {
  high: '优先',
  medium: '常规',
  low: '可后置',
}

/**
 * OutlineCards（技能卡）：复习提纲——模块清单可勾选进度（localStorage 记账），
 * 每条要点挂来源、可一键追问；优先级用徽章标注。
 */
export function OutlineCards({ outlines, onAsk }: {
  outlines: OutlineSuggestion[]
  onAsk?: (text: string) => void
}) {
  const [checks, setChecks] = useState<Record<string, boolean>>(loadOutlineChecks)

  const total = outlines.reduce(
    (sum, outline) => sum + outline.modules.reduce((moduleSum, module) => moduleSum + module.items.length, 0),
    0,
  )
  const done = outlines.reduce((sum, outline) => sum + outline.modules.reduce((moduleSum, module, mi) => {
    const counted = module.items.filter((_, ii) => checks[`${outline.id}-${mi}-${ii}`])
    return moduleSum + counted.length
  }, 0), 0)

  function toggle(key: string) {
    setChecks((current) => {
      const next = { ...current, [key]: !current[key] }
      writeStorage(OUTLINE_CHECKS_KEY, JSON.stringify(next))
      return next
    })
  }

  if (outlines.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="复习提纲">
      <small className="agent-cards-title">📋 复习提纲 · 勾选记进度，条目可继续追问</small>
      {outlines.map((outline) => (
        <article key={outline.id} className="agent-card agent-card-outline" role="listitem">
          <header className="outline-head">
            <strong>{outline.title}</strong>
            <span className="outline-progress tabular-nums">
              {done}/{total}
              <span className="outline-progress-track" aria-hidden="true">
                <span
                  className="outline-progress-fill"
                  style={{ width: total ? `${Math.round((done / total) * 100)}%` : '0%' }}
                />
              </span>
            </span>
          </header>
          {outline.modules.map((module, mi) => (
            <section key={`${outline.id}-${mi}`} className="outline-module">
              <h4 className="outline-module-title">
                <span className={`outline-priority is-${module.priority}`}>{PRIORITY_LABELS[module.priority]}</span>
                {module.title}
              </h4>
              <ul className="outline-items">
                {module.items.map((item, ii) => {
                  const key = `${outline.id}-${mi}-${ii}`
                  const checked = Boolean(checks[key])
                  return (
                    <li key={key} className={checked ? 'is-checked' : undefined}>
                      <label className="outline-item-row cursor-interaction">
                        <input type="checkbox" checked={checked} onChange={() => toggle(key)} />
                        <span className="outline-item-point">{item.point}</span>
                      </label>
                      <span className="outline-item-actions">
                        {item.ref ? <small className="outline-item-ref">{item.ref}</small> : null}
                        {onAsk && (
                          <button
                            type="button"
                            className="outline-item-ask cursor-interaction"
                            onClick={() => onAsk(`再展开讲讲「${item.point}」，结合课程资料给我解释。`)}
                          >问这个</button>
                        )}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </article>
      ))}
    </div>
  )
}

/**
 * ContrastCards（技能卡）：易混概念——左右分栏对比表 + 记忆锚点，
 * 每对可「就这对考考我」直接带着概念上下文调出题技能（技能联动）。
 */
export function ContrastCards({ contrasts, onAsk }: {
  contrasts: ContrastSuggestion[]
  onAsk?: (text: string) => void
}) {
  if (contrasts.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="易混概念对比">
      <small className="agent-cards-title">⚡ 易混概念 · 左右对比 + 一键针对出题</small>
      {contrasts.map((contrast) => (
        <article key={contrast.id} className="agent-card agent-card-contrast" role="listitem">
          {contrast.pairs.map((pair, index) => (
            <section key={`${contrast.id}-${index}`} className="contrast-pair">
              <header className="contrast-pair-head">
                <strong className="contrast-name">{pair.a}</strong>
                <span className="contrast-vs" aria-hidden="true">vs</span>
                <strong className="contrast-name">{pair.b}</strong>
              </header>
              <p className="contrast-core">{pair.core}</p>
              <div className="contrast-table" role="table" aria-label={`${pair.a} 与 ${pair.b} 对比`}>
                <div className="contrast-row contrast-row-head" role="row">
                  <span role="columnheader">维度</span>
                  <span role="columnheader">{pair.a}</span>
                  <span role="columnheader">{pair.b}</span>
                </div>
                {pair.dimensions.map((dimension, di) => (
                  <div key={`${contrast.id}-${index}-${di}`} className="contrast-row" role="row">
                    <span className="contrast-dim" role="rowheader">{dimension.name}</span>
                    <span role="cell">{dimension.a}</span>
                    <span role="cell">{dimension.b}</span>
                  </div>
                ))}
              </div>
              <footer className="contrast-pair-foot">
                {pair.anchor ? <span className="contrast-anchor">🧠 {pair.anchor}</span> : <span />}
                {onAsk && (
                  <button
                    type="button"
                    className="contrast-quiz cursor-interaction"
                    onClick={() => onAsk(`就「${pair.a}」和「${pair.b}」的区别出一道题考考我`)}
                  >就这对考考我</button>
                )}
              </footer>
            </section>
          ))}
        </article>
      ))}
    </div>
  )
}

/**
 * MessageSkillCards：挂在「产生它的那轮回答」正下方的技能卡集合。
 * 数据源是 useConversation 的 agentSuggestionsByMessage（按助手消息 id 分桶），
 * 该是哪轮就是哪轮，不再全部堆在对话底部。
 */
export function MessageSkillCards({ suggestions, courseId, onAsk }: {
  suggestions?: AgentSuggestion[]
  courseId?: string
  onAsk?: (text: string) => void
}) {
  if (!suggestions || suggestions.length === 0) return null
  const quizzes = suggestions.filter(
    (item): item is Extract<AgentSuggestion, { type: 'quiz' }> => item.type === 'quiz',
  )
  const outlines = suggestions.filter(
    (item): item is Extract<AgentSuggestion, { type: 'review_outline' }> => item.type === 'review_outline',
  )
  const contrasts = suggestions.filter(
    (item): item is Extract<AgentSuggestion, { type: 'concept_contrast' }> => item.type === 'concept_contrast',
  )
  const proposals = suggestions.filter(
    (item): item is Extract<AgentSuggestion, { type: 'knowledge_proposal' }> => item.type === 'knowledge_proposal',
  )
  if (quizzes.length === 0 && outlines.length === 0 && contrasts.length === 0 && proposals.length === 0) return null
  return (
    <>
      <QuizCards quizzes={quizzes} courseId={courseId} />
      <OutlineCards outlines={outlines} onAsk={onAsk} />
      <ContrastCards contrasts={contrasts} onAsk={onAsk} />
      <KnowledgeProposalCards suggestions={proposals} />
    </>
  )
}
