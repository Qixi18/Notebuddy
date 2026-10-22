import { useEffect, useRef, useState } from 'react'

import type { Course } from '../../types'
import type { AskScope } from '../conversation/useConversation'

/** 会话归属的下一步选择：全局可查 / 整门课程 / 锁定笔记（后两者带二级选择器） */
export type ScopeNext = { kind: 'global' | 'course' | 'note'; targetId?: string; targetTitle?: string }

/**
 * 答疑主线顶部的常驻上下文条：范围 chip + 本轮检索摘要。
 * 范围三档：全局可查（无目标）/ 整门课程（选课程→切换课程上下文）/ 锁定笔记（选笔记）。
 * 范围是会话级属性：新会话默认「全局可查」，发出首条消息后锁定，不再允许修改。
 *
 * 学习目标不在这里设置：后端会按问题关键词自动推断（见 ai/discipline.py），
 * 界面恒定给一个默认值只会短路那条推断，已移除。
 */
export function AssistantContextBar({ courses, scopeKind, scopeTargetId, scopeTargetTitle, onScopeChange, onSelectCourse, onOpenNotePicker, summary, scopeMenuOpen, onScopeMenuChange, locked, lockHint, onLockedAttempt }: {
  courses: Course[]
  scopeKind: 'global' | 'course' | 'note'
  scopeTargetId?: string
  scopeTargetTitle?: string
  onScopeChange: (next: ScopeNext) => void
  onSelectCourse: (courseId: string) => void
  /** 选「锁定笔记」时打开笔记选择框（按课程筛 + 按名称搜） */
  onOpenNotePicker: () => void
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
  const [submenu, setSubmenu] = useState<'course' | 'note' | null>(null)
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

  const label = scopeKind === 'global'
    ? '全局可查'
    : scopeKind === 'note'
      ? (scopeTargetTitle ?? '锁定笔记')
      : '整门课程'

  function pick(kind: 'global' | 'course' | 'note') {
    if (kind === 'global') {
      onScopeChange({ kind: 'global' })
      onScopeMenuChange(false)
    } else if (kind === 'note') {
      /* 锁定笔记走独立选择框：平铺列表既搜不了也换不了课程 */
      onScopeMenuChange(false)
      onOpenNotePicker()
    } else {
      setSubmenu((current) => (current === kind ? null : kind))
    }
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
            <button
              type="button"
              role="menuitemradio"
              aria-checked={scopeKind === 'note'}
              className={`workspace-scope-option${scopeKind === 'note' ? ' is-active' : ''}`}
              onClick={() => pick('note')}
            >锁定笔记</button>

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
          </div>
        )}
      </div>

      {/* 锁定预告：首条消息发出后范围就定死，把约束前置到用户做选择的那一刻，
          而不是等他自己改了范围却被后端静默忽略时才提示。 */}
      {!locked ? (
        <span className="workspace-scope-lock-tip">首条消息后范围将锁定</span>
      ) : null}

      {summary && (
        <span className="workspace-context-summary">
          本轮检索 {summary.materials} 份资料 · {summary.items} 段原文
        </span>
      )}
    </div>
  )
}
