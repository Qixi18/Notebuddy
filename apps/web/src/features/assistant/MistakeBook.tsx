import { useEffect, useMemo, useState } from 'react'

import { api } from '../../api'
import type { QuizMistake, ReviewArtifactDto } from '../../api/quiz'
import { ContrastCards, OutlineCards } from './AgentCards'

/**
 * 复习面板（v6 §7 学习闭环，由错题本扩展而来）：三种产物统一管理——
 * - 题目：最近一次仍错（或收藏/标记）的题，支持搜索、筛选、收藏、标记、移出；
 * - 复习提纲 / 易混概念：技能产出已落库（review_artifacts），支持收藏与删除。
 *
 * 「让 AI 讲讲这道题」把题目 + 我的答案 + 正确答案注入会话，先诊断错因再讲（引导模式优先）；
 * 「重练同类」把该题考点作为 focus 交给 generate_quiz 重新出题。
 */

type ReviewTab = 'items' | 'outline' | 'contrast'
type ItemFilter = 'all' | 'favorite' | 'marked'

const TAB_LABELS: Record<ReviewTab, string> = {
  items: `题目`,
  outline: `复习提纲`,
  contrast: `易混概念`,
}

export function MistakeBook({ open, courseId, courseName, onClose, onExplain, onRetry }: {
  open: boolean
  courseId?: string
  courseName?: string
  onClose: () => void
  onExplain: (prompt: string) => void
  onRetry: (prompt: string) => void
}) {
  const [tab, setTab] = useState<ReviewTab>('items')

  const [mistakes, setMistakes] = useState<QuizMistake[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()

  const [artifacts, setArtifacts] = useState<ReviewArtifactDto[]>([])
  const [artifactsLoading, setArtifactsLoading] = useState(false)
  const [artifactsError, setArtifactsError] = useState<string>()

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ItemFilter>('all')
  const [flagBusy, setFlagBusy] = useState<string>()
  /* 移出复习的二次确认：3 秒内再点才生效，超时/失焦复位 */
  const [confirmDismiss, setConfirmDismiss] = useState<string>()
  useEffect(() => {
    if (!confirmDismiss) return
    const timer = window.setTimeout(() => setConfirmDismiss(undefined), 3000)
    return () => window.clearTimeout(timer)
  }, [confirmDismiss])

  useEffect(() => {
    if (!open || !courseId || tab !== 'items') return
    let alive = true
    setLoading(true)
    setError(undefined)
    void api.listMistakes(courseId)
      .then((items) => { if (alive) setMistakes(items) })
      .catch((cause: unknown) => {
        if (alive) setError(cause instanceof Error ? cause.message : '错题读取失败，请重试')
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [open, courseId, tab])

  useEffect(() => {
    if (!open || !courseId || tab === 'items') return
    const kind = tab === 'outline' ? 'review_outline' as const : 'concept_contrast' as const
    let alive = true
    setArtifactsLoading(true)
    setArtifactsError(undefined)
    void api.listReviewArtifacts(courseId, kind, true)
      .then((items) => { if (alive) setArtifacts(items) })
      .catch((cause: unknown) => {
        if (alive) setArtifactsError(cause instanceof Error ? cause.message : '复习产物读取失败，请重试')
      })
      .finally(() => { if (alive) setArtifactsLoading(false) })
    return () => { alive = false }
  }, [open, courseId, tab])

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  /* 题目筛选：搜索（题干）+ 视图（全部/收藏/已标记）；移出的题后端已不返回 */
  const visibleMistakes = useMemo(() => {
    const keyword = query.trim()
    return mistakes.filter((item) => {
      if (filter === 'favorite' && !item.favorite) return false
      if (filter === 'marked' && !item.marked) return false
      if (keyword && !item.stem.includes(keyword)) return false
      return true
    })
  }, [mistakes, query, filter])

  const groups = useMemo(() => {
    const map = new Map<string, { title: string; items: QuizMistake[] }>()
    for (const item of visibleMistakes) {
      const key = item.material_id ?? '__no_material__'
      if (!map.has(key)) {
        map.set(key, { title: item.material_title ?? '未指定课件（笔记或全课出题）', items: [] })
      }
      map.get(key)!.items.push(item)
    }
    return [...map.values()]
  }, [visibleMistakes])

  async function updateFlags(item: QuizMistake, patch: { favorite?: boolean; marked?: boolean; dismissed?: boolean }) {
    if (flagBusy) return
    setFlagBusy(item.item_id)
    setError(undefined)
    try {
      const updated = await api.setItemFlags(item.item_id, patch)
      setMistakes((current) => {
        if (updated.dismissed) return current.filter((entry) => entry.item_id !== item.item_id)
        return current.map((entry) => (
          entry.item_id === item.item_id
            ? { ...entry, favorite: updated.favorite, marked: updated.marked }
            : entry
        ))
      })
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : '操作失败，请重试')
    } finally {
      setFlagBusy(undefined)
    }
  }

  async function patchArtifact(artifact: ReviewArtifactDto, patch: { favorite?: boolean; dismissed?: boolean }) {
    setArtifactsError(undefined)
    try {
      const updated = await api.updateArtifact(artifact.id, patch)
      setArtifacts((current) => current.map((entry) => (
        entry.id === artifact.id
          ? { ...entry, favorite: updated.favorite, dismissed: updated.dismissed }
          : entry
      )))
    } catch (cause: unknown) {
      setArtifactsError(cause instanceof Error ? cause.message : '操作失败，请重试')
    }
  }

  if (!open) return null

  /* 在册（面板可见）与已移出（折叠区，可恢复）分开；搜索只作用于在册 */
  const activeArtifacts = artifacts.filter((artifact) => !artifact.dismissed)
  const dismissedArtifacts = artifacts.filter((artifact) => artifact.dismissed)
  const outlineSuggestions = activeArtifacts
    .filter((artifact) => artifact.kind === 'review_outline')
    .map((artifact) => {
      const payload = artifact.payload as {
        title?: string
        modules?: Array<{ title: string; priority?: 'high' | 'medium' | 'low'; items: Array<{ point: string; ref?: string }> }>
      }
      const modules = payload.modules ?? []
      return {
        type: 'review_outline' as const, id: artifact.id, artifact_id: artifact.id,
        favorite: artifact.favorite, title: payload.title ?? artifact.title,
        module_count: modules.length,
        item_count: modules.reduce((sum: number, module: { items?: unknown[] }) => sum + (module.items?.length ?? 0), 0),
        modules: modules.map((module) => ({ ...module, priority: module.priority ?? ('medium' as const) })),
      }
    })
  const contrastSuggestions = activeArtifacts
    .filter((artifact) => artifact.kind === 'concept_contrast')
    .map((artifact) => {
      const payload = artifact.payload as {
        pairs?: Array<{ a: string; b: string; core: string; anchor?: string; dimensions: Array<{ name: string; a: string; b: string }> }>
      }
      const pairs = payload.pairs ?? []
      return {
        type: 'concept_contrast' as const, id: artifact.id, artifact_id: artifact.id,
        favorite: artifact.favorite, pair_count: pairs.length, pairs,
      }
    })

  /* 提纲/对比的搜索：提纲匹配标题/模块/要点，对比匹配概念名/核心区别/维度/锚点 */
  const keyword = query.trim()
  const visibleOutlines = keyword
    ? outlineSuggestions.filter((outline) =>
        outline.title.includes(keyword)
        || outline.modules.some((module) =>
          module.title.includes(keyword)
          || module.items.some((item) => item.point.includes(keyword))))
    : outlineSuggestions
  const visibleContrasts = keyword
    ? contrastSuggestions.filter((contrast) =>
        contrast.pairs.some((pair) => [
          pair.a, pair.b, pair.core, pair.anchor ?? '',
          ...pair.dimensions.flatMap((dimension) => [dimension.name, dimension.a, dimension.b]),
        ].some((field) => (field ?? '').includes(keyword))))
    : contrastSuggestions
  const searchPlaceholder = tab === 'items'
    ? '搜索题干…'
    : tab === 'outline' ? '搜索提纲（标题 / 模块 / 要点）…' : '搜索概念 / 区别 / 维度…'
  const artifactEmptyText = tab === 'outline'
    ? { none: '还没有复习提纲。', hint: '在答疑里说「整理成复习提纲」，生成的提纲会出现在这里。', miss: '没有匹配的提纲，换个关键词试试。' }
    : { none: '还没有易混概念对比。', hint: '在答疑里说「这一讲有哪些易混概念」，生成的对比卡会出现在这里。', miss: '没有匹配的对比，换个关键词试试。' }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card mistake-book"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="复习"
      >
        <header className="mistake-head">
          <div>
            <h3>复习</h3>
            <p className="mistake-sub">{courseName ?? '本课程'}</p>
          </div>
          <button type="button" className="ghost-button" onClick={onClose}>关闭</button>
        </header>

        <nav className="review-tabs" role="tablist" aria-label="复习分类">
          {(Object.keys(TAB_LABELS) as ReviewTab[]).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`review-tab cursor-interaction${tab === key ? ' is-active' : ''}`}
              onClick={() => setTab(key)}
            >{TAB_LABELS[key]}</button>
          ))}
        </nav>

        <div className="mistake-body">
          <div className="review-toolbar">
            <input
              type="search"
              className="review-search"
              placeholder={searchPlaceholder}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="搜索复习内容"
            />
            {tab === 'items' && (
              <div className="review-filters" role="group" aria-label="题目筛选">
                {([['all', '全部'], ['favorite', '★ 收藏'], ['marked', '⚑ 已标记']] as Array<[ItemFilter, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`review-filter cursor-interaction${filter === key ? ' is-active' : ''}`}
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >{label}</button>
                ))}
              </div>
            )}
          </div>
          {tab === 'items' && (
            <>
              {error && <p className="workspace-agent-notice" role="alert">{error}</p>}
              {!error && !loading && visibleMistakes.length === 0 && (
                <div className="mistake-empty">
                  <p>{mistakes.length === 0 ? '还没有错题。' : '没有符合筛选条件的题目。'}</p>
                  <span>让桌宠「考考我」，答错的题会自动收集到这里；同一道题后来答对，就会移出。收藏的题答对了也保留。</span>
                </div>
              )}
              {groups.map((group) => (
                <section key={group.title} className="mistake-group">
                  <h4 className="mistake-group-title">{group.title}</h4>
                  {group.items.map((item) => (
                    <article key={item.item_id} className="mistake-item">
                      <p className="mistake-stem">
                        <span className="mistake-seq" aria-hidden="true">{item.seq}</span>
                        {item.stem}
                        {item.wrong_count > 1 && <span className="mistake-wrong-count">错过 {item.wrong_count} 次</span>}
                        {item.favorite && <span className="mistake-flag-tag">★</span>}
                        {item.marked && <span className="mistake-flag-tag">⚑</span>}
                      </p>
                      <p className="mistake-answers">
                        <span className="mistake-yours">我的答案：{item.last_answer || '（空）'}</span>
                        <span className="mistake-right">正确答案：{item.answer}</span>
                      </p>
                      {item.explanation && <p className="mistake-why">{item.explanation}</p>}
                      <div className="mistake-actions">
                        <button type="button" className="mistake-action-primary" onClick={() => onExplain(explainPrompt(item))}>
                          让 AI 讲讲这道题
                        </button>
                        <button type="button" className="mistake-action" onClick={() => onRetry(retryPrompt(item))}>
                          重练同类
                        </button>
                        <span className="mistake-source">{item.quiz_title}</span>
                        <span className="mistake-item-flags">
                          <button
                            type="button"
                            className={`artifact-action cursor-interaction${item.favorite ? ' is-active' : ''}`}
                            disabled={flagBusy === item.item_id}
                            onClick={() => updateFlags(item, { favorite: !item.favorite })}
                          >{item.favorite ? '★' : '☆'}</button>
                          <button
                            type="button"
                            className={`artifact-action cursor-interaction${item.marked ? ' is-active' : ''}`}
                            disabled={flagBusy === item.item_id}
                            onClick={() => updateFlags(item, { marked: !item.marked })}
                          >⚑</button>
                          <button
                            type="button"
                            className={`artifact-action cursor-interaction${confirmDismiss === item.item_id ? ' is-danger' : ''}`}
                            disabled={flagBusy === item.item_id}
                            title="移出复习"
                            onClick={() => {
                              if (confirmDismiss === item.item_id) {
                                updateFlags(item, { dismissed: true })
                                setConfirmDismiss(undefined)
                              } else {
                                setConfirmDismiss(item.item_id)
                              }
                            }}
                            onBlur={() => setConfirmDismiss((current) => (current === item.item_id ? undefined : current))}
                          >{confirmDismiss === item.item_id ? '确认移出' : '✕'}</button>
                        </span>
                      </div>
                    </article>
                  ))}
                </section>
              ))}
            </>
          )}

          {tab === 'outline' && (
            <>
              {artifactsError && <p className="workspace-agent-notice" role="alert">{artifactsError}</p>}
              {!artifactsError && !artifactsLoading && outlineSuggestions.length === 0 && (
                <div className="mistake-empty"><p>{artifactEmptyText.none}</p><span>{artifactEmptyText.hint}</span></div>
              )}
              {!artifactsError && outlineSuggestions.length > 0 && visibleOutlines.length === 0 && (
                <div className="mistake-empty"><p>{artifactEmptyText.miss}</p></div>
              )}
              {/* 面板里的提纲同样可追问：走 onExplain 同一条会话通道（关面板 → 填草稿） */}
              <OutlineCards outlines={visibleOutlines} onAsk={onExplain} />
              <DismissedZone
                items={dismissedArtifacts.filter((artifact) => artifact.kind === 'review_outline')}
                onRestore={(artifact) => patchArtifact(artifact, { dismissed: false })}
              />
            </>
          )}

          {tab === 'contrast' && (
            <>
              {artifactsError && <p className="workspace-agent-notice" role="alert">{artifactsError}</p>}
              {!artifactsError && !artifactsLoading && contrastSuggestions.length === 0 && (
                <div className="mistake-empty"><p>{artifactEmptyText.none}</p><span>{artifactEmptyText.hint}</span></div>
              )}
              {!artifactsError && contrastSuggestions.length > 0 && visibleContrasts.length === 0 && (
                <div className="mistake-empty"><p>{artifactEmptyText.miss}</p></div>
              )}
              <ContrastCards contrasts={visibleContrasts} onAsk={onExplain} />
              <DismissedZone
                items={dismissedArtifacts.filter((artifact) => artifact.kind === 'concept_contrast')}
                onRestore={(artifact) => patchArtifact(artifact, { dismissed: false })}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** 错因诊断优先：把「题目 + 我的答案 + 正确答案」一起注入，避免 agent 只看到残题瞎猜。 */
function explainPrompt(item: QuizMistake): string {
  const stem = item.stem.length > 160 ? `${item.stem.slice(0, 160)}…` : item.stem
  const lines = [
    '我刚做错了一道题。请先诊断我的错因，再针对性地讲，不要一上来就给答案。',
    `题目：${stem}`,
    `我的答案：${item.last_answer || '（空）'}`,
    `正确答案：${item.answer}`,
  ]
  if (item.explanation.trim()) lines.push(`参考解释：${item.explanation.trim()}`)
  return lines.join('\n')
}

/** 重练：把题干当考点线索交给 generate_quiz（focus），由 agent 决定素材与题量。 */
function retryPrompt(item: QuizMistake): string {
  const stem = item.stem.length > 80 ? `${item.stem.slice(0, 80)}…` : item.stem
  return `针对这道错题的考点再出两道题考考我：${stem}`
}

/** 已移出产物折叠区：软移除的提纲/对比在这里列出，可一键恢复到复习在册。 */
function DismissedZone({ items, onRestore }: {
  items: ReviewArtifactDto[]
  onRestore: (artifact: ReviewArtifactDto) => void
}) {
  const [open, setOpen] = useState(false)
  if (items.length === 0) return null
  return (
    <section className="dismissed-zone">
      <button
        type="button"
        className="dismissed-toggle cursor-interaction"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >已移出（{items.length}）{open ? '▲' : '▼'}</button>
      {open && (
        <ul className="dismissed-list">
          {items.map((artifact) => (
            <li key={artifact.id}>
              <span className="dismissed-title">{artifact.title}</span>
              <button type="button" className="artifact-action cursor-interaction" onClick={() => onRestore(artifact)}>
                ↩ 恢复
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
