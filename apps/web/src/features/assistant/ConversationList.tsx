import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import type { Conversation, Course } from '../../types'
import { api } from '../../api'
import { buildHistory, conversationTime, conversationTimeLabel } from '../conversation/conversationGroups'
import {
  ConversationContextMenu,
  DeleteConversationDialog,
  RenameConversationDialog,
  type ConversationMenuState,
} from './ConversationContextMenu'

function GlobeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M4 12h16M12 4c2.5 2.6 2.5 13.4 0 16M12 4c-2.5 2.6-2.5 13.4 0 16" />
    </svg>
  )
}

function CourseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="4" width="7" height="7" rx="1.6" />
      <rect x="13" y="4" width="7" height="7" rx="1.6" />
      <rect x="4" y="13" width="7" height="7" rx="1.6" />
      <rect x="13" y="13" width="7" height="7" rx="1.6" />
    </svg>
  )
}

function NoteIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7 4h7l4 4v12H7z" />
      <path d="M14 4v4h4" />
    </svg>
  )
}

/**
 * 会话标题：平时省略号截断；鼠标悬浮且确实溢出时，自动向尾部滚动把标题看全。
 * 溢出量纯 CSS 拿不到，只能量：量完写进 --nb-marquee-shift 交给 CSS 动画，
 * 悬浮期间在「原位 → 末尾 → 原位」之间往复，离开即回位。
 */
function ConversationTitle({ text }: { text: string }) {
  const outerRef = useRef<HTMLSpanElement>(null)
  const innerRef = useRef<HTMLSpanElement>(null)
  const [marquee, setMarquee] = useState<{ shift: number; seconds: number } | null>(null)

  function start() {
    const outer = outerRef.current
    const inner = innerRef.current
    if (!outer || !inner) return
    const overflow = inner.scrollWidth - outer.clientWidth
    /* 没溢出就别滚，省得白白加动画 */
    if (overflow <= 2) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    /* 距离越远给越长时间，保证阅读速度大致恒定 */
    setMarquee({ shift: overflow, seconds: Math.min(7, Math.max(2.4, overflow / 22)) })
  }

  function stop() {
    setMarquee(null)
  }

  return (
    <span ref={outerRef} className="workspace-conv-title" onMouseEnter={start} onMouseLeave={stop}>
      <span
        ref={innerRef}
        className={`workspace-conv-title-text${marquee ? ' is-marqueeing' : ''}`}
        style={marquee ? ({
          '--nb-marquee-shift': `${marquee.shift}px`,
          animationDuration: `${marquee.seconds}s`,
        } as CSSProperties) : undefined}
      >
        {text}
      </span>
    </span>
  )
}

/**
 * 左栏历史：课程 → 整门课程 / 各篇笔记两级。
 * 时间只作为行尾信息，不参与分组；折叠状态记在组件内。
 */
export function ConversationList({ conversations, courses, conversationId, busy, error, onSelect, onRename, onDelete }: {
  conversations: Conversation[]
  courses: Course[]
  conversationId?: string
  busy: boolean
  /** 最近一次操作（重命名/删除）的失败原因，用于在对话框内显示 */
  error?: string
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => Promise<boolean>
  onDelete: (id: string) => Promise<boolean>
}) {
  const sections = useMemo(() => buildHistory(conversations, courses), [conversations, courses])
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [menu, setMenu] = useState<ConversationMenuState>(null)
  const [renameTarget, setRenameTarget] = useState<{ id: string; title: string } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string>()

  if (conversations.length === 0) {
    return <p className="workspace-conv-empty">还没有历史会话，提问后会自动保存。</p>
  }

  function toggle(id: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function requestRename(id: string, title: string) {
    setMenu(null)
    setActionError(undefined)
    setRenameTarget({ id, title })
  }

  function requestDelete(id: string, title: string) {
    setMenu(null)
    setActionError(undefined)
    setDeleteTarget({ id, title })
  }

  /* 失败时保留对话框并把原因显示出来，避免「点了没反应」 */
  async function confirmRename(title: string) {
    if (!renameTarget) return
    setSaving(true)
    setActionError(undefined)
    const ok = await onRename(renameTarget.id, title)
    setSaving(false)
    if (ok) setRenameTarget(null)
    else setActionError(error || '重命名失败，请检查后端服务后重试。')
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setSaving(true)
    setActionError(undefined)
    const ok = await onDelete(deleteTarget.id)
    setSaving(false)
    if (ok) setDeleteTarget(null)
    else setActionError(error || '删除失败，请检查后端服务后重试。')
  }

  function renderItem(item: Conversation) {
    const active = item.id === conversationId
    return (
      <button
        key={item.id}
        type="button"
        className={`workspace-conv-item${active ? ' is-active' : ''}`}
        aria-current={active ? 'true' : undefined}
        disabled={busy}
        onClick={() => onSelect(item.id)}
        onContextMenu={(event) => {
          event.preventDefault()
          setMenu({ x: event.clientX, y: event.clientY, id: item.id, title: item.title })
        }}
      >
        <ConversationTitle text={item.title || '未命名会话'} />
        <span className="workspace-conv-time">{conversationTimeLabel(item)}</span>
      </button>
    )
  }

  return (
    <>
      <nav className="workspace-conv" aria-label="会话历史">
      {sections.map((section) => {
        const sectionCollapsed = collapsed.has(section.id)
        /* 「整门课程」这一组单独折叠：用 id + 后缀做 key，不会和课程头 / 笔记组冲突 */
        const courseGroupKey = `${section.id}:course`
        const courseGroupCollapsed = collapsed.has(courseGroupKey)
        return (
          <section className="workspace-history-group" key={section.id}>
            <button
              type="button"
              className="workspace-history-head"
              aria-expanded={!sectionCollapsed}
              onClick={() => toggle(section.id)}
            >
              <span className="workspace-history-icon" aria-hidden="true">
                {section.kind === 'global' ? <GlobeIcon /> : <CourseIcon />}
              </span>
              <span className="workspace-history-name">
                <b>{section.title}</b>
                <small>{section.meta}</small>
              </span>
              <span className="workspace-history-chevron" aria-hidden="true">▾</span>
            </button>

            {!sectionCollapsed && (
              <div className="workspace-history-body">
                {section.items.length > 0 && section.kind === 'course' && (
                  <button
                    type="button"
                    className="workspace-history-sub"
                    aria-expanded={!courseGroupCollapsed}
                    onClick={() => toggle(courseGroupKey)}
                  >
                    <span className="workspace-history-subtitle">整门课程</span>
                    <span className="workspace-history-count">{section.items.length}</span>
                    <span className="workspace-history-chevron is-small" aria-hidden="true">▾</span>
                  </button>
                )}
                {!courseGroupCollapsed && section.items.map(renderItem)}

                {section.notes.map((note) => {
                  const noteCollapsed = collapsed.has(note.id)
                  return (
                    <div className="workspace-history-note" key={note.id}>
                      <button
                        type="button"
                        className="workspace-history-sub workspace-history-sub-note"
                        aria-expanded={!noteCollapsed}
                        onClick={() => toggle(note.id)}
                      >
                        <span className="workspace-history-note-icon" aria-hidden="true"><NoteIcon /></span>
                        <span className="workspace-history-subtitle">{note.title}</span>
                        <span className="workspace-history-count">{note.items.length}</span>
                        <span className="workspace-history-chevron is-small" aria-hidden="true">▾</span>
                      </button>
                      {!noteCollapsed && note.items.map(renderItem)}
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        )
      })}
      </nav>

      <ConversationContextMenu
        state={menu}
        onClose={() => setMenu(null)}
        onRename={requestRename}
        onDelete={requestDelete}
      />
      <RenameConversationDialog
        open={renameTarget !== null}
        initialTitle={renameTarget?.title ?? ''}
        saving={saving}
        error={actionError}
        onSubmit={(title) => void confirmRename(title)}
        onCancel={() => setRenameTarget(null)}
      />
      <DeleteConversationDialog
        open={deleteTarget !== null}
        title={deleteTarget?.title ?? ''}
        saving={saving}
        error={actionError}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  )
}

/** 命中片段按关键词二次定位并高亮（大小写不敏感，中文逐字匹配） */
function HighlightedSnippet({ snippet, keyword }: { snippet: string; keyword: string }) {
  const lowered = snippet.toLowerCase()
  const needle = keyword.toLowerCase()
  const parts: Array<{ text: string; hit: boolean }> = []
  let cursor = 0
  while (cursor < snippet.length) {
    const index = lowered.indexOf(needle, cursor)
    if (index < 0 || !needle) {
      parts.push({ text: snippet.slice(cursor), hit: false })
      break
    }
    if (index > cursor) parts.push({ text: snippet.slice(cursor, index), hit: false })
    parts.push({ text: snippet.slice(index, index + needle.length), hit: true })
    cursor = index + needle.length
  }
  return (
    <span className="workspace-palette-snippet">
      {parts.map((part, index) => (part.hit ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>))}
    </span>
  )
}

/** Ctrl+K 会话搜索命令面板：两级结果——会话（标题命中，本地过滤）+ 消息（内容命中，后端搜索） */
export function ConversationSearch({ conversations, conversationId, courseId, onSelect, onSelectMessage, onClose }: {
  conversations: Conversation[]
  conversationId?: string
  courseId?: string
  onSelect: (id: string) => void
  /** 点消息命中：打开该会话并定位高亮该条消息 */
  onSelectMessage: (conversationId: string, messageId: string) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [messageResults, setMessageResults] = useState<Awaited<ReturnType<typeof api.searchMessages>>>([])
  const [messageSearchBusy, setMessageSearchBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  useEffect(() => {
    const value = query.trim()
    if (!courseId || value.length < 2) { setMessageResults([]); setMessageSearchBusy(false); return }
    let active = true
    setMessageSearchBusy(true)
    const timer = window.setTimeout(() => {
      void api.searchMessages(courseId, value).then((results) => {
        if (active) setMessageResults(results)
      }).catch(() => {
        if (active) setMessageResults([])
      }).finally(() => {
        if (active) setMessageSearchBusy(false)
      })
    }, 180)
    return () => { active = false; window.clearTimeout(timer) }
  }, [courseId, query])

  const results = useMemo(() => {
    const sorted = [...conversations].sort((a, b) => conversationTime(b) - conversationTime(a))
    const keyword = query.trim().toLowerCase()
    const matched = keyword
      ? sorted.filter((item) => (item.title || '').toLowerCase().includes(keyword))
      : sorted
    return matched.slice(0, 8)
  }, [conversations, query])

  return (
    <div className="workspace-palette-backdrop" onClick={onClose}>
      <div
        className="workspace-palette"
        role="dialog"
        aria-modal="true"
        aria-label="搜索会话"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索会话标题或消息内容…"
          aria-label="搜索会话标题或消息内容"
          maxLength={120}
          onKeyDown={(event) => {
            if (event.key === 'Escape') { onClose(); return }
            if (event.key !== 'Enter') return
            /* 与会话标题命中优先，其次才是消息命中；消息命中要带上 messageId 才能定位 */
            if (results[0]) { onSelect(results[0].id); onClose(); return }
            const hit = messageResults[0]
            if (hit) { onSelectMessage(hit.conversation_id, hit.message_id); onClose() }
          }}
        />
        {results.length === 0 ? (
          <p className="workspace-palette-empty">没有匹配的会话</p>
        ) : (
          <ul className="workspace-palette-list">
            {results.map((item) => {
              const active = item.id === conversationId
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={active ? 'is-active' : undefined}
                    aria-current={active ? 'true' : undefined}
                    onClick={() => { onSelect(item.id); onClose() }}
                  >
                    <span>{item.title || '未命名会话'}</span>
                    <small>{conversationTimeLabel(item)}</small>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {query.trim().length >= 2 && (
          <section className="workspace-palette-messages" aria-label="消息内容匹配">
            <strong>消息内容{messageSearchBusy ? ' · 搜索中…' : ''}</strong>
            {messageResults.length === 0 && !messageSearchBusy
              ? <p className="workspace-palette-empty">没有匹配的消息</p>
              : <ul className="workspace-palette-list">
                {messageResults.map((hit) => (
                  <li key={hit.message_id}>
                    <button type="button" onClick={() => { onSelectMessage(hit.conversation_id, hit.message_id); onClose() }}>
                      <span>{hit.conversation_title} · {hit.message_role === 'user' ? '你' : 'AI'}</span>
                      <HighlightedSnippet snippet={hit.snippet} keyword={query.trim()} />
                    </button>
                  </li>
                ))}
              </ul>}
          </section>
        )}
        <p className="workspace-palette-hint">Enter 打开第一条 · Esc 关闭</p>
      </div>
    </div>
  )
}
