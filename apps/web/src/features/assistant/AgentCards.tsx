import { useEffect, useState } from 'react'

import { api } from '../../api'
import type { AgentSuggestion } from '../../api/agentStream'
import type { QuizDto } from '../../api/quiz'
import { readStorage, writeStorage } from '../../utils/safeStorage'
import { AssistantMessageMarkdown } from './AssistantMessageContent'
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
      <small className="agent-cards-title">笔记修改建议 · 勾选要应用的变更块，确认后才会写入</small>
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
      <small className="agent-cards-title">知识节点提议 · 到课程知识图谱审核后才会进入图谱</small>
      {suggestions.map((proposal) => (
        <article key={proposal.id} className="agent-card agent-card-info" role="listitem">
          <p className="agent-card-body">提议新增知识点「{proposal.name}」</p>
        </article>
      ))}
    </div>
  )
}

/** QuizCards（v6 P10）：agent 出的自测卷——拉题目、作答、服务端判分讲评。 */
export function QuizCards({ quizzes, courseId, onAsk }: {
  quizzes: Array<{ type: 'quiz'; id: string; quiz_id: string; title: string; item_count: number }>
  courseId?: string
  /** 判错后的「让 AI 讲讲这道题」：把题目+我的答案+正确答案注入草稿 */
  onAsk?: (prompt: string) => void
}) {
  const [quizzesById, setQuizzesById] = useState<Record<string, QuizDto>>({})
  /* 拉取状态：loading=首次列表中；missing=列表里没有（已完成/超出窗口），按 id 精确补拉；
      failed=补拉也失败（网络/服务异常），给明确失败态而不是永远「正在加载」 */
  const [state, setState] = useState<'loading' | 'missing' | 'failed' | 'ready'>('loading')

  /* 先拉课程 active 卷子；不在列表里的卷子（已答完、或早于列表窗口）按建议里的 id 单卷补拉 */
  useEffect(() => {
    if (!courseId || quizzes.length === 0) return
    let alive = true
    setState((current) => (current === 'ready' ? current : 'loading'))
    const wanted = quizzes.filter((quiz) => !quizzesById[quiz.quiz_id]).map((quiz) => quiz.quiz_id)
    void api.listQuizzes(courseId, 'active')
      .then(async (items) => {
        if (!alive) return
        const map: Record<string, QuizDto> = { ...quizzesById }
        for (const quiz of items) map[quiz.id] = quiz
        const missing = quizzes
          .map((quiz) => quiz.quiz_id)
          .filter((id) => !map[id])
        const fetched = await Promise.all(missing.map(async (id) => {
          try {
            return await api.getQuiz(id)
          } catch {
            return null
          }
        }))
        if (!alive) return
        for (const quiz of fetched) {
          if (quiz) map[quiz.id] = quiz
        }
        setQuizzesById(map)
        /* 有任何建议卷子彻底拉不到（连单卷直取都 404/异常）→ 失败态，而不是假加载 */
        setState(quizzes.some((quiz) => !map[quiz.quiz_id]) ? 'missing' : 'ready')
      })
      .catch(() => { if (alive) setState('failed') })
    return () => { alive = false }
    // quizzesById 不进依赖：重拉只在建议集合变化时发生，避免每次判分回写都刷新
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, quizzes.length])

  /* 模型出的标题可能已带「（N题）」，模板不再重复拼一次 */
  function displayTitle(title: string, itemCount: number): string {
    return /（\d+\s*题）$/.test(title) ? title : `${title}（${itemCount} 题）`
  }

  if (quizzes.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="自测卷">
      <small className="agent-cards-title">自测卷 · 作答后系统自动判分讲评（答案不出现在页面上）</small>
      {quizzes.map((quiz) => {
        const dto = quizzesById[quiz.quiz_id]
        if (!dto) {
          return (
            <article key={quiz.quiz_id} className="agent-card agent-card-info" role="listitem">
              <p className="agent-card-body">
                📄 {displayTitle(quiz.title, quiz.item_count)}
                {!courseId || state === 'loading' ? ' · 正在加载题目…' : ''}
                {state === 'missing' && ' · 这份卷子已完成或已归档，可在复习面板回看作答记录'}
                {state === 'failed' && ' · 题目读取失败，请稍后刷新重试'}
              </p>
            </article>
          )
        }
        return <QuizCard key={quiz.quiz_id} quiz={dto} onAsk={onAsk} />
      })}
    </div>
  )
}

function QuizCard({ quiz, onAsk }: { quiz: QuizDto; onAsk?: (prompt: string) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [graded, setGraded] = useState<Record<string, { correct: boolean; answer: string; explanation: string; comment: string; points?: Array<{ point: string; hit: boolean }> }>>({})
  const [busyId, setBusyId] = useState<string>()
  const [error, setError] = useState<string>()
  /* 题目级用户状态（§7）：初值取库（随卷子下发），判分后可收藏/标记，与复习面板同源 */
  const [flagOverrides, setFlagOverrides] = useState<Record<string, { favorite?: boolean; marked?: boolean }>>({})
  const [flagBusy, setFlagBusy] = useState<string>()

  const gradedCount = Object.keys(graded).length
  const correctCount = Object.values(graded).filter((entry) => entry.correct).length
  const allGraded = gradedCount === quiz.items.length
  /* 难度标签（§7 第二批）：用户自定义原话，未指定时为「自适应」 */
  const difficulty = quiz.items.find((item) => item.difficulty)?.difficulty

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

  async function toggleItemFlag(item: QuizDto['items'][number], patch: { favorite?: boolean; marked?: boolean }) {
    if (flagBusy) return
    setFlagBusy(item.id)
    setError(undefined)
    try {
      const updated = await api.setItemFlags(item.id, patch)
      setFlagOverrides((current) => ({
        ...current,
        [item.id]: {
          favorite: updated.favorite,
          marked: updated.marked,
        },
      }))
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : '操作失败，请重试')
    } finally {
      setFlagBusy(undefined)
    }
  }

  return (
    <article className="agent-card quiz-paper" role="listitem">
      <header className="quiz-paper-head">
        <span className="quiz-paper-badge">自测卷</span>
        <strong className="quiz-paper-title">{quiz.title}</strong>
        {difficulty && <span className="quiz-paper-difficulty">{difficulty}</span>}
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
                {/* B1 结构化判分：简答题的要点命中明细（选择题后端返回空数组，不渲染） */}
                {verdict.points && verdict.points.length > 0 && (
                  <ul className="quiz-points" aria-label="要点命中情况">
                    {verdict.points.map((point, index) => (
                      <li key={`${item.id}-point-${index}`} className={point.hit ? 'is-hit' : 'is-missed'}>
                        <span aria-hidden="true">{point.hit ? '✓' : '✗'}</span>
                        {point.point}
                      </li>
                    ))}
                  </ul>
                )}
                {/* 答错教学闭环：带着「题目 + 我的答案 + 正确答案」去问，agent 才讲得准 */}
                {!verdict.correct && onAsk && (
                  <button
                    type="button"
                    className="quiz-verdict-ask cursor-interaction"
                    onClick={() => onAsk(explainQuizPrompt(item.stem, picked, verdict))}
                  >让 AI 讲讲这道题</button>
                )}
                {/* 题目收藏/标记（§7）：与复习面板同源，收藏的题答对也不出册 */}
                <div className="quiz-item-flags">
                  <button
                    type="button"
                    className={`artifact-action cursor-interaction${flagOverrides[item.id]?.favorite ? ' is-active' : ''}`}
                    disabled={flagBusy === item.id}
                    onClick={() => toggleItemFlag(item, { favorite: !(flagOverrides[item.id]?.favorite ?? Boolean(item.favorite)) })}
                  >{(flagOverrides[item.id]?.favorite ?? Boolean(item.favorite)) ? '★ 已收藏' : '☆ 收藏'}</button>
                  <button
                    type="button"
                    className={`artifact-action cursor-interaction${flagOverrides[item.id]?.marked ? ' is-active' : ''}`}
                    disabled={flagBusy === item.id}
                    onClick={() => toggleItemFlag(item, { marked: !(flagOverrides[item.id]?.marked ?? Boolean(item.marked)) })}
                  >{(flagOverrides[item.id]?.marked ?? Boolean(item.marked)) ? '⚑ 已标记' : '⚑ 标记'}</button>
                </div>
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
/** 复习产物卡上的收藏/移出动作：产出已落库（artifact_id），跨会话在复习面板同样可见。
    「移出复习」是软移除：只从复习面板消失，本会话卡片保留，可随时恢复。
    挂载时从 review_artifacts 回读一次收藏/移出真源——消息快照是生成时刻旧值，不回读会状态回退。 */
function useArtifactActions(artifactIds: string[]) {
  const [favOverrides, setFavOverrides] = useState<Record<string, boolean>>({})
  const [dismissedOverrides, setDismissedOverrides] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState<string>()
  const idsKey = artifactIds.join('|')

  useEffect(() => {
    if (!idsKey) return
    let alive = true
    void api.listArtifactStates(idsKey.split('|').filter(Boolean))
      .catch(() => [])
      .then((items) => {
        if (!alive || !Array.isArray(items)) return
        setFavOverrides((current) => {
          const next = { ...current }
          for (const item of items) {
            if (item.id in current) continue
            next[item.id] = Boolean(item.favorite)
          }
          return next
        })
        setDismissedOverrides((current) => {
          const next = { ...current }
          for (const item of items) {
            if (item.id in current) continue
            next[item.id] = Boolean(item.dismissed)
          }
          return next
        })
      })
    return () => { alive = false }
  }, [idsKey])

  const favoriteOf = (suggestion: { artifact_id?: string; favorite?: boolean }): boolean | undefined => {
    if (!suggestion.artifact_id) return undefined
    return favOverrides[suggestion.artifact_id] ?? Boolean(suggestion.favorite)
  }
  const dismissedOf = (suggestion: { artifact_id?: string }): boolean => {
    if (!suggestion.artifact_id) return false
    return dismissedOverrides[suggestion.artifact_id] ?? false
  }

  async function toggleFavorite(artifactId: string, next: boolean) {
    setBusy(artifactId)
    try {
      const updated = await api.updateArtifact(artifactId, { favorite: next })
      setFavOverrides((current) => ({ ...current, [artifactId]: updated.favorite }))
    } finally {
      setBusy(undefined)
    }
  }

  async function setDismissed(artifactId: string, next: boolean) {
    setBusy(artifactId)
    try {
      const updated = await api.updateArtifact(artifactId, { dismissed: next })
      setDismissedOverrides((current) => ({ ...current, [artifactId]: updated.dismissed }))
    } finally {
      setBusy(undefined)
    }
  }

  return { favoriteOf, toggleFavorite, dismissedOf, setDismissed, busy }
}

function ArtifactActions({ artifactId, favorite, dismissed, busy, onFavorite, onDismissed }: {
  artifactId?: string
  favorite?: boolean
  dismissed?: boolean
  busy?: string
  onFavorite: (artifactId: string, next: boolean) => void
  onDismissed: (artifactId: string, next: boolean) => void
}) {
  /* 移出复习需二次确认：第一下变「确认移出」，3 秒内再点才生效，超时自动复位；恢复是立即的 */
  const [confirming, setConfirming] = useState(false)
  useEffect(() => {
    if (!confirming) return
    const timer = window.setTimeout(() => setConfirming(false), 3000)
    return () => window.clearTimeout(timer)
  }, [confirming])

  if (!artifactId) return null
  return (
    <span className="artifact-actions">
      <button
        type="button"
        className={`artifact-action cursor-interaction${favorite ? ' is-active' : ''}`}
        disabled={busy === artifactId}
        title={favorite ? '取消收藏' : '收藏到复习'}
        onClick={() => onFavorite(artifactId, !favorite)}
      >{favorite ? '★ 已收藏' : '☆ 收藏'}</button>
      {dismissed ? (
        <button
          type="button"
          className="artifact-action cursor-interaction"
          disabled={busy === artifactId}
          title="恢复到复习面板"
          onClick={() => onDismissed(artifactId, false)}
        >↩ 恢复复习</button>
      ) : (
        <button
          type="button"
          className={`artifact-action cursor-interaction${confirming ? ' is-danger' : ''}`}
          disabled={busy === artifactId}
          title="从复习面板移出（会话卡片保留）"
          onClick={() => (confirming ? onDismissed(artifactId, true) : setConfirming(true))}
          onBlur={() => setConfirming(false)}
        >{confirming ? '确认移出？' : '✕ 移出复习'}</button>
      )}
    </span>
  )
}

export function OutlineCards({ outlines, onAsk }: {
  outlines: OutlineSuggestion[]
  onAsk?: (text: string) => void
}) {
  const [checks, setChecks] = useState<Record<string, boolean>>(loadOutlineChecks)
  const { favoriteOf, toggleFavorite, dismissedOf, setDismissed, busy } = useArtifactActions(
    outlines.map((outline) => outline.artifact_id).filter((id): id is string => Boolean(id)),
  )
  /* 移出复习后卡片仍保留在会话里（软移除），只标记状态 */
  const visible = outlines

  const total = visible.reduce(
    (sum, outline) => sum + outline.modules.reduce((moduleSum, module) => moduleSum + module.items.length, 0),
    0,
  )
  const done = visible.reduce((sum, outline) => sum + outline.modules.reduce((moduleSum, module, mi) => {
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

  if (visible.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="复习提纲">
      <small className="agent-cards-title">复习提纲 · 勾选记进度，条目可继续追问</small>
      {visible.map((outline) => (
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
          <div className="outline-artifact-bar">
            <ArtifactActions
              artifactId={outline.artifact_id}
              favorite={favoriteOf(outline)}
              dismissed={dismissedOf(outline)}
              busy={busy}
              onFavorite={toggleFavorite}
              onDismissed={setDismissed}
            />
          </div>
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
                        {/* 要点常含公式（|ξ-η|² 一类），走 KaTeX 渲染而不是裸文本 */}
                        <span className="outline-item-point"><AssistantMessageMarkdown content={item.point} /></span>
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
  const { favoriteOf, toggleFavorite, dismissedOf, setDismissed, busy } = useArtifactActions(
    contrasts.map((contrast) => contrast.artifact_id).filter((id): id is string => Boolean(id)),
  )
  const visible = contrasts
  if (visible.length === 0) return null
  return (
    <div className="agent-cards" role="list" aria-label="易混概念对比">
      <small className="agent-cards-title">易混概念 · 左右对比 + 一键针对出题</small>
      {visible.map((contrast) => (
        <article key={contrast.id} className="agent-card agent-card-contrast" role="listitem">
          <div className="outline-artifact-bar">
            <ArtifactActions
              artifactId={contrast.artifact_id}
              favorite={favoriteOf(contrast)}
              dismissed={dismissedOf(contrast)}
              busy={busy}
              onFavorite={toggleFavorite}
              onDismissed={setDismissed}
            />
          </div>
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
                {pair.anchor ? <span className="contrast-anchor">{pair.anchor}</span> : <span />}
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
      <QuizCards quizzes={quizzes} courseId={courseId} onAsk={onAsk} />
      <OutlineCards outlines={outlines} onAsk={onAsk} />
      <ContrastCards contrasts={contrasts} onAsk={onAsk} />
      <KnowledgeProposalCards suggestions={proposals} />
    </>
  )
}

/** 判错后注入会话的问题：题目、我的答案、正确答案三件齐备，agent 才能诊断错因而不是瞎猜。 */
function explainQuizPrompt(
  stem: string,
  picked: string,
  verdict: { answer: string; explanation: string },
): string {
  const head = stem.length > 160 ? `${stem.slice(0, 160)}…` : stem
  const lines = [
    '我刚做错了一道题。请先诊断我的错因，再针对性地讲，不要一上来就给答案。',
    `题目：${head}`,
    `我的答案：${picked || '（空）'}`,
    `正确答案：${verdict.answer}`,
  ]
  if (verdict.explanation.trim()) lines.push(`参考解释：${verdict.explanation.trim()}`)
  return lines.join('\n')
}
