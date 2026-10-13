import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { featurePath, useWorkspace } from './AppLayout'
import { SourceCard } from './SourceCard'
import { TeacherCharacter } from './TeacherCharacter'
import { ApiError, api } from '../api'
import type { Material } from '../types'
import { teacherPersonaMeta } from '../features/persona/personas'
import { modeLabelsShort } from '../features/assistant/answerMeta'
import {
  clampDockWidth,
  DOCK_WIDTH_DEFAULT,
  DOCK_WIDTH_SNAP,
  DOCK_WIDTH_STEP,
} from '../features/assistant/dockLayout'

type AssistantDockProps = {
  /** 当前宽度，由外壳持有并持久化 */
  width: number
  onWidthChange: (width: number) => void
  onClose: () => void
  /** 拖拽期间通知外壳关掉过渡并禁用选中，避免宽度落后鼠标 */
  onResizeStateChange: (resizing: boolean) => void
}

/** 参考项目悬浮坞的三个快捷提示，对应「解释 / 检索 / 总结」三能力 */
const QUICK_PROMPTS: Array<{ label: string; prompt: string }> = [
  { label: '解释概念', prompt: '用更直白的话解释一下这里的核心概念，并举一个例子。' },
  { label: '检索课件', prompt: '课程资料里还有哪些相关内容？请标出出处。' },
  { label: '总结要点', prompt: '把主要内容总结成几条要点。' },
]

/** 只有正打开着笔记的页面才谈得上「写入当前笔记」 */
const NOTE_PATH = /\/(notebook|notes\/[^/]+)$/

/**
 * 悬浮答疑坞。与答疑页共用 useConversation 的同一份会话，
 * 因此这里问过的问题会落库，切到答疑页也能看到完整历史。
 *
 * 抽屉形态与能力参照 notebuddy_myself 的「伴读智能体」悬浮坞：
 *   · 不是浮层遮罩，而是主内容区右侧的挤压式抽屉，展开时正文自动让位；
 *   · 左边缘分界条可拖拽实时调宽（双击复位、拖太窄自动收合、宽度记忆）；
 *   · 上下文感知：说明当前挂在哪门课 / 哪份课件上，范围可手动收窄；
 *   · 检索显性化：回答后附来源清单，可跳回课件；
 *   · 回写：把上一条回答追加到当前笔记末尾（只追加，不覆盖）。
 */
export function AssistantDock({ width, onWidthChange, onClose, onResizeStateChange }: AssistantDockProps) {
  const {
    courseId,
    courses,
    conversationCourseId,
    materials: workspaceMaterials,
    selectedNote,
    noteDirty,
    noteSaving,
    openMaterialSource,
    refreshCurrentNotes,
    teacherPersona,
    conversation,
  } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const [draft, setDraft] = useState('')
  const [scopeMaterialId, setScopeMaterialId] = useState<string>()
  const [ownMaterials, setOwnMaterials] = useState<Material[]>([])
  const [writeBackBusy, setWriteBackBusy] = useState(false)
  const [writeBackNotice, setWriteBackNotice] = useState<string>()
  const messagesRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const persona = teacherPersonaMeta(teacherPersona)
  const conversationCourse = courses.find((item) => item.id === conversationCourseId)
  const fellBackToRecent = Boolean(conversationCourseId) && !courseId

  /* 课程页上工作区已经加载了同一门课的资料，直接复用；其余页面（首页、回收站…）自己拉一份，
     否则「限定资料」在那些页面上会是空的 */
  const reusingWorkspaceMaterials = Boolean(conversationCourseId) && conversationCourseId === courseId
  useEffect(() => {
    if (!conversationCourseId || reusingWorkspaceMaterials) { setOwnMaterials([]); return }
    let active = true
    void api.listMaterials(conversationCourseId)
      .then((items) => { if (active) setOwnMaterials(items) })
      .catch(() => { if (active) setOwnMaterials([]) })
    return () => { active = false }
  }, [conversationCourseId, reusingWorkspaceMaterials])
  const scopeMaterials = reusingWorkspaceMaterials ? workspaceMaterials : ownMaterials
  /* 范围落不到实处时收回「整门课程」，而不是让请求带着一个已失效的 id */
  useEffect(() => {
    if (scopeMaterialId && !scopeMaterials.some((item) => item.id === scopeMaterialId)) setScopeMaterialId(undefined)
  }, [scopeMaterialId, scopeMaterials])

  const messages = conversation.messages
  const lastMessage = messages[messages.length - 1]
  const lastAnswer = [...messages].reverse().find((message) => message.role === 'assistant' && message.id !== 'local-greeting')
  const bottomKey = `${messages.length}:${lastMessage?.content.length ?? 0}:${conversation.busy}`

  /* 消息变化后重新定位视口：新回复很长时把它的开头对齐到顶部（读到的是正文开头），
     等待回复或最后一条是自己提问时落到最底部 */
  useEffect(() => {
    const node = messagesRef.current
    if (!node) return
    const last = node.lastElementChild as HTMLElement | null
    if (last?.classList.contains('assistant-dock-message-assistant')) {
      node.scrollTop += Math.round(last.getBoundingClientRect().top - node.getBoundingClientRect().top) - 2
    } else {
      node.scrollTop = node.scrollHeight
    }
  }, [bottomKey])

  /* 外壳总宽：上限比例要按它算，否则窄窗口下抽屉能把正文挤没。
     拿不到外壳（理论上不会）时退回窗口宽度。 */
  function containerWidth(grip: HTMLElement): number {
    const shell = grip.closest('.app-shell')
    return shell instanceof HTMLElement && shell.clientWidth > 0 ? shell.clientWidth : window.innerWidth
  }

  /* 拖拽用 pointer 事件：鼠标 / 触控 / 触控笔一套手势。
     监听挂在 window 上，指针滑出那条 12px 细线也不会中断拖拽。 */
  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const grip = event.currentTarget
    const startX = event.clientX
    const startWidth = width
    /* 原始值单独记一份：clamp 会把宽度托到下限，收合判定必须看用户手上真实的拖动量 */
    let rawWidth = startWidth
    try {
      grip.setPointerCapture?.(event.pointerId)
    } catch {
      /* jsdom 等环境未实现指针捕获，忽略即可，拖拽本身不依赖它 */
    }
    onResizeStateChange(true)

    const handleMove = (moveEvent: PointerEvent) => {
      rawWidth = startWidth - (moveEvent.clientX - startX) // 往左拖 = 变宽
      onWidthChange(clampDockWidth(rawWidth, containerWidth(grip)))
    }
    const handleEnd = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleEnd)
      window.removeEventListener('pointercancel', handleEnd)
      onResizeStateChange(false)
      if (rawWidth < DOCK_WIDTH_SNAP) {
        // 拖得太窄：视为「我要关掉它」，宽度记回默认值，下次唤起仍是舒服的尺寸
        onWidthChange(DOCK_WIDTH_DEFAULT)
        onClose()
      }
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleEnd)
    window.addEventListener('pointercancel', handleEnd)
  }

  function nudgeWidth(event: ReactKeyboardEvent<HTMLDivElement>) {
    const grip = event.currentTarget
    if (event.key === 'ArrowLeft') onWidthChange(clampDockWidth(width + DOCK_WIDTH_STEP, containerWidth(grip)))
    else if (event.key === 'ArrowRight') onWidthChange(clampDockWidth(width - DOCK_WIDTH_STEP, containerWidth(grip)))
    else if (event.key === 'Home') onWidthChange(DOCK_WIDTH_DEFAULT)
    else return
    event.preventDefault()
  }

  async function submitQuestion(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!conversationCourseId || !text || conversation.busy) return
    setDraft('')
    setWriteBackNotice(undefined)
    if (!await conversation.ask(text, { materialId: scopeMaterialId })) setDraft(text)
  }

  /* 回写：只追加、绝不覆盖原文；编辑器里有未保存改动时直接禁用，避免把用户的字冲掉 */
  const notePath = NOTE_PATH.test(location.pathname)
  const canWriteBack = Boolean(selectedNote && lastAnswer && notePath && !noteDirty && !noteSaving) && !writeBackBusy
  const writeBackHint = !notePath
    ? '先在课程笔记本里打开一条笔记，再回来点这里'
    : noteDirty ? '笔记有未保存的修改，先保存再回写' : !lastAnswer ? '还没有可写入的回答' : '追加到当前笔记末尾，原有内容不改动'

  async function writeBackToNote() {
    if (!selectedNote || !lastAnswer || !canWriteBack) return
    setWriteBackBusy(true)
    setWriteBackNotice(undefined)
    try {
      const merged = `${selectedNote.content_markdown.replace(/\s*$/, '')}\n\n${lastAnswer.content.trim()}\n`
      const updated = await api.updateNote(selectedNote.id, merged, selectedNote.revision_number)
      await refreshCurrentNotes()
      setWriteBackNotice(`已追加到《${updated.title}》末尾，原有内容未改动。`)
    } catch (cause) {
      setWriteBackNotice(cause instanceof ApiError && cause.status === 409
        ? '这条笔记刚在别处更新过，请先刷新笔记再回写。'
        : cause instanceof Error ? cause.message : '写入笔记失败')
    } finally {
      setWriteBackBusy(false)
    }
  }

  /* 来源卡片只在「抽屉挂靠的课程 == 当前浏览的课程」时可点：
     否则跳过去会带着另一门课的页码，把用户引到错的地方 */
  const sourcesOpenable = Boolean(courseId) && conversationCourseId === courseId

  const scopeLabel = scopeMaterialId
    ? `课件《${scopeMaterials.find((item) => item.id === scopeMaterialId)?.lecture_title ?? '未命名'}》`
    : '整门课程'
  const contextLabel = notePath && selectedNote ? `当前笔记《${selectedNote.title}》` : scopeLabel

  return (
    <aside className="assistant-dock" aria-label="课程学习助手">
      <div
        className="assistant-dock-grip"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整答疑坞宽度，双击复位"
        title="拖拽调整宽度 · 双击复位"
        tabIndex={0}
        onPointerDown={startResize}
        onDoubleClick={() => onWidthChange(DOCK_WIDTH_DEFAULT)}
        onKeyDown={nudgeWidth}
      ><i /><i /><i /></div>

      <header className="assistant-dock-heading">
        <span className="assistant-dock-mark" aria-hidden="true">✦</span>
        <div><strong>{persona.name} · 学习助手</strong><small>{conversationCourse?.name ?? '尚无可提问的课程'}</small></div>
        <button className="assistant-dock-close" type="button" onClick={onClose} aria-label="收起答疑坞" title="收起答疑坞">✕</button>
      </header>

      {/* 侧边答疑坞展示完整立绘：不用 compact（那是 48px 头像的尺寸语义），
          animated 让它与首页一致走连续帧雪碧图，而不是静态立绘 */}
      <div className="assistant-dock-teacher"><TeacherCharacter animated status={conversation.busy ? 'thinking' : 'idle'} character={teacherPersona} /></div>

      {conversationCourseId ? (
        <>
          {/* 上下文行：说明这轮问答挂在哪门课、哪个范围上，落回最近课程时讲清原因 */}
          <p className="assistant-dock-context" aria-live="polite">
            上下文：<strong>「{conversationCourse?.name ?? '课程'}」</strong> · {contextLabel}
            {fellBackToRecent ? <em>（按最近访问自动选定）</em> : null}
          </p>

          {scopeMaterials.length > 0 && (
            <label className="assistant-dock-scope">作用范围
              <select value={scopeMaterialId ?? ''} onChange={(event) => setScopeMaterialId(event.target.value || undefined)} aria-label="本次提问的作用范围">
                <option value="">整门课程</option>
                {scopeMaterials.map((material) => <option key={material.id} value={material.id}>{material.lecture_title}</option>)}
              </select>
            </label>
          )}

          <div className="assistant-dock-messages" aria-live="polite" ref={messagesRef}>
            {messages.map((message, index) => (
              <article className={`assistant-dock-message assistant-dock-message-${message.role}`} key={`${message.role}-${index}-${message.content.slice(0, 12)}`}>
                <small>{message.role === 'user' ? '你' : persona.name}</small>
                {/* 老师回答走与答疑页同一条 Markdown 管线（remark-math + rehype-katex），
                    否则 ### / ** / 列表会以原始标记直接显示出来；自己的提问保持纯文本 */}
                {message.role === 'assistant'
                  ? <div className="assistant-dock-answer"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{message.content}</ReactMarkdown></div>
                  : <p>{message.content}</p>}
                {/* 检索能力显性化：说清这轮是否命中了课件 */}
                {message.role === 'assistant' && message.mode ? <span className="assistant-dock-mode">{modeLabelsShort[message.mode] ?? '课程资料检索'}</span> : null}
                {message.role === 'assistant' && message.sources?.length ? (
                  <div className="assistant-dock-sources">
                    <small>回答依据 · {message.sources.length} 条</small>
                    {message.sources.map((source, sourceIndex) => source.source_type === 'web' && source.url
                      ? <a className="source-card web-source-card" key={source.url} href={source.url} target="_blank" rel="noreferrer">
                        <span className="source-card-icon" aria-hidden="true">↗</span>
                        <span className="source-card-body"><span className="source-card-meta">网络补充 · {source.site_name}</span><strong>{source.title}</strong><small>{source.snippet}</small></span>
                      </a>
                      : source.material_id && source.page_number
                        ? <SourceCard
                          key={`${source.material_id}-${source.page_number}-${sourceIndex}`}
                          title={source.lecture_title ?? '课程资料'}
                          pageNumber={source.page_number}
                          locationLabel={source.location_label}
                          quote={source.snippet}
                          onOpen={sourcesOpenable ? () => {
                            openMaterialSource(source.material_id!, source.page_number ?? undefined)
                            if (courseId) navigate(featurePath(courseId, 'materials'))
                          } : undefined}
                        />
                        : null)}
                  </div>
                ) : null}
              </article>
            ))}
          </div>

          <div className="assistant-dock-quick">
            {QUICK_PROMPTS.map((item) => (
              <button key={item.label} type="button" disabled={conversation.busy} onClick={() => { setDraft(item.prompt); inputRef.current?.focus() }}>{item.label}</button>
            ))}
          </div>

          <form className="assistant-dock-form" onSubmit={submitQuestion}>
            <textarea ref={inputRef} aria-label="快速提问" placeholder={`问问「${conversationCourse?.name ?? '当前课程'}」…`} value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} />
            <div className="assistant-dock-actions">
              <button type="button" className="assistant-dock-ghost" disabled={conversation.busy} onClick={() => { setWriteBackNotice(undefined); void conversation.startNewConversation() }}>新建对话</button>
              <button type="button" className="assistant-dock-ghost" disabled={!canWriteBack} title={writeBackHint} onClick={() => void writeBackToNote()}>{writeBackBusy ? '写入中…' : '写入当前笔记'}</button>
              <button type="submit" className="assistant-dock-send" disabled={!draft.trim() || conversation.busy}>{conversation.busy ? '思考中…' : '发送'}</button>
            </div>
            <div className="assistant-dock-links"><Link to={featurePath(conversationCourseId, 'assistant')}>打开完整答疑</Link></div>
          </form>

          {(writeBackNotice || conversation.error) && (
            <p className={`assistant-dock-status${writeBackNotice && !conversation.error ? '' : ' assistant-dock-status-error'}`} role="status">
              {conversation.error ?? writeBackNotice}
            </p>
          )}
        </>
      ) : (
        <div className="assistant-dock-empty">
          <p>还没有可提问的课程。创建课程并上传学习资料后，悬浮坞就能基于课件回答。</p>
          <Link className="text-button" to="/">创建课程</Link>
        </div>
      )}
    </aside>
  )
}
