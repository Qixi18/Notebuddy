import { useEffect, useRef, useState } from 'react'

import type { Course } from '../../types'

/** 会话归属的下一步选择：全局可查 / 整门课程 / 锁定一本 Notebook。 */
export type ScopeNext = { kind: 'global' | 'course' | 'notebook' }

export type ScopeNotebook = { id: string; title: string }

/**
 * 答疑主线顶部的常驻上下文条：范围 chip + 本轮检索摘要。
 * 范围三档：全局可查 / 整门课程 / 锁定一本 Notebook（走 Notebook 核验链）。
 * 范围是会话级属性：新会话默认「整门课程」，发出首条消息后锁定，不再允许修改。
 *
 * 学习目标不在这里设置：后端会按问题关键词自动推断（见 ai/discipline.py），
 * 界面恒定给一个默认值只会短路那条推断，已移除。
 */
export function AssistantContextBar({ courses, scopeKind, scopeTargetId, scopeNotebookId, notebooks, onScopeChange, onSelectCourse, onSelectNotebook, summary, scopeMenuOpen, onScopeMenuChange, locked, lockHint, onLockedAttempt }: {
  courses: Course[]
  scopeKind: 'global' | 'course' | 'notebook'
  scopeTargetId?: string
  /** 当前锁定的 Notebook id（scopeKind === 'notebook' 时高亮用） */
  scopeNotebookId?: string
  /** 当前课程的 Notebook 列表；为空时不展示 Notebook 档 */
  notebooks?: ScopeNotebook[]
  onScopeChange: (next: ScopeNext) => void
  onSelectCourse: (courseId: string) => void
  onSelectNotebook?: (notebookId: string) => void
  summary?: { materials: number; items: number } | null
  scopeMenuOpen: boolean
  onScopeMenuChange: (open: boolean) => void
  /** 当前会话已发出消息 → 范围锁定 */
  locked?: boolean
  /** 是否展示「已锁定」提示 */
  lockHint?: boolean
  /** 锁定态下点击范围 chip 的回调（弹出提示，而不是打开菜单） */
  onLockedAttempt?: () => void
}) {
  const [submenu, setSubmenu] = useState<'course' | 'notebook' | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!scopeMenuOpen) { setSubmenu(null); return }
    function onDocClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) onScopeMenuChange(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [scopeMenuOpen, onScopeMenuChange])

  /* 会话一旦锁定（已发出消息），菜单不再可开 */
  useEffect(() => {
    if (locked) { setSubmenu(null); onScopeMenuChange(false) }
  }, [locked, onScopeMenuChange])

  const selectedNotebook = notebooks?.find((item) => item.id === scopeNotebookId)
  const label = scopeKind === 'global'
    ? '全局可查'
    : scopeKind === 'notebook'
      ? `Notebook《${selectedNotebook?.title ?? '未选择'}》`
      : '整门课程'

  function pick(kind: 'global' | 'course' | 'notebook') {
    if (kind === 'global') {
      onScopeChange({ kind: 'global' })
      onScopeMenuChange(false)
      return
    }
    if (kind === 'notebook') {
      setSubmenu((current) => (current === kind ? null : kind))
      return
    }
    setSubmenu((current) => (current === kind ? null : kind))
  }

  return (
    <div className="workspace-context" aria-label="提问上下文" ref={rootRef}>
      <div className="workspace-chip workspace-scope">
        <span>范围</span>
        <button
          type="button"
          className={`workspace-scope-trigger${locked ? ' is-locked' : ''}`}
          aria-haspopup={locked ? undefined : 'true'}
          aria-expanded={locked ? undefined : scopeMenuOpen}
          title={locked ? '对话已开始回答，范围已锁定；点「＋新对话」可重新选择' : '修改提问范围'}
          onClick={() => (locked ? onLockedAttempt?.() : onScopeMenuChange(!scopeMenuOpen))}
        >
          <strong>{label}</strong>
          {locked
            ? (
              <svg className="workspace-scope-lock" viewBox="0 0 24 24" width="11" height="11" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4" y="10.5" width="16" height="10.5" rx="2.5" />
                <path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" />
              </svg>
            )
            : <span className="workspace-scope-caret" aria-hidden="true">▾</span>}
        </button>

        {lockHint && (
          <span className="workspace-scope-lock-hint" role="status">
            对话已开始回答，范围已锁定；点「＋新对话」可重新选择
          </span>
        )}

        {scopeMenuOpen && !locked && (
          <div className="workspace-scope-menu" role="menu">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={scopeKind === 'global'}
              className={`workspace-scope-option${scopeKind === 'global' ? ' is-active' : ''}`}
              onClick={() => pick('global')}
            >全局可查</button>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={scopeKind === 'course'}
              className={`workspace-scope-option${scopeKind === 'course' ? ' is-active' : ''}`}
              onClick={() => pick('course')}
            >整门课程</button>
            {notebooks && onSelectNotebook ? (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={scopeKind === 'notebook'}
                className={`workspace-scope-option${scopeKind === 'notebook' ? ' is-active' : ''}`}
                onClick={() => pick('notebook')}
              >一本 Notebook（核验链）</button>
            ) : null}
            {submenu === 'course' && (
              <div className="workspace-scope-picker" role="menu">
                <span className="workspace-scope-picker-title">锁定哪一门课程</span>
                <div className="workspace-scope-picker-list">
                  {courses.map((course) => (
                    <button
                      key={course.id}
                      type="button"
                      className={`workspace-scope-pick${course.id === scopeTargetId ? ' is-active' : ''}`}
                      onClick={() => { onSelectCourse(course.id); onScopeMenuChange(false) }}
                    >{course.name}</button>
                  ))}
                </div>
              </div>
            )}
            {submenu === 'notebook' && notebooks?.length ? (
              <div className="workspace-scope-picker" role="menu">
                <span className="workspace-scope-picker-title">锁定哪一本 Notebook</span>
                <div className="workspace-scope-picker-list">
                  {notebooks.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`workspace-scope-pick${item.id === scopeNotebookId ? ' is-active' : ''}`}
                      onClick={() => { onSelectNotebook?.(item.id); onScopeMenuChange(false) }}
                    >{item.title}</button>
                  ))}
                </div>
              </div>
            ) : null}
            {submenu === 'notebook' && !notebooks?.length ? (
              <div className="workspace-scope-picker" role="menu">
                <span className="workspace-scope-picker-title">这门课还没有 Notebook</span>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* 锁定预告：首条消息发出后范围就定死，把约束前置到用户做选择的那一刻，
          而不是等他自己改了范围却被后端静默忽略时才提示。 */}
      {!locked ? (
        <span className="workspace-scope-lock-tip">首条消息后范围将锁定</span>
      ) : null}

      {scopeKind === 'notebook' ? (
        <span className="workspace-context-summary">Notebook 范围：答案先读正文，再用原始资料核验</span>
      ) : null}

      {summary && (
        <span className="workspace-context-summary">
          本轮检索 {summary.materials} 份资料 · {summary.items} 段原文
        </span>
      )}
    </div>
  )
}
