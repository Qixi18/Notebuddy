import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { featurePath, useWorkspace } from '../components/AppLayout'
import { TeacherCharacter, type TeacherStatus } from '../components/TeacherCharacter'
import { api } from '../api'
import { AssistantComposer } from '../features/assistant/AssistantComposer'
import { AssistantContextBar, type ScopeNext } from '../features/assistant/AssistantContextBar'
import { AssistantThread } from '../features/assistant/AssistantThread'
import { ConversationList, ConversationSearch } from '../features/assistant/ConversationList'
import { NoteScopePicker } from '../features/assistant/NoteScopePicker'
import { NoteSuggestionCards } from '../features/assistant/AgentCards'
import { useNoteSuggestions } from '../features/assistant/useNoteSuggestions'
import { NotePreviewDialog } from '../features/assistant/NotePreviewDialog'
import { ChangesPanel, type NoteChangeItem } from '../features/assistant/ChangesPanel'
import { MistakeBook } from '../features/assistant/MistakeBook'
import { TermDialog } from '../features/assistant/TermDialog'
import { teacherPersonaMeta } from '../features/persona/personas'
import { PetAvatar, type PetAvatarHandle } from '../features/pet/PetAvatar'
import type { PetMode } from '../features/pet/petLayout'
import { loadPetPlacement, savePetPlacement } from '../features/pet/petStorage'
import { reportQuestion } from '../features/pet/petEggs'
import type { AskScope } from '../features/conversation/useConversation'
import type { AgentReadingContext, AgentScope } from '../api/agent'

/**
 * 答疑桌宠 · 三区工作台：
 * 左栏（桌宠 + 会话历史）/ 中栏（上下文条 + 对话 + 输入）/ 右栏（依据台，可收起）。
 * 本页只做编排；会话状态仍来自 useConversation 单一来源。
 */
export function AssistantPage() {
  const {
    course,
    courseId,
    courses,
    materials,
    notes,
    courseContentLoading,
    openMaterialSource,
    conversation,
    refreshCurrentNotes,
  } = useWorkspace()
  const { askAgent, stopAgent, ready, busy, hasMessages, messages, renameConversation, deleteConversation, agentRun } = conversation
  const navigate = useNavigate()
  const location = useLocation()

  const composerRef = useRef<HTMLTextAreaElement>(null)
  const composerAreaRef = useRef<HTMLDivElement>(null)
  const petRef = useRef<PetAvatarHandle>(null)
  const initialQuestionSent = useRef(false)

  const [draft, setDraft] = useState('')
  /* 范围默认「全局可查」；新会话开出后、首条消息发出前可改，发出后锁定 */
  const [scopeKind, setScopeKind] = useState<'global' | 'course' | 'note'>('global')
  const [scopeTargetId, setScopeTargetId] = useState<string>()
  const [scopeTargetTitle, setScopeTargetTitle] = useState<string>()
  /* 课件收窄（P3）：消息级参数，仅 course 档随请求发送；不写会话 scope、不触发锁定。
     切范围档 / 切会话 / 切课程时复位（见 changeScope 与下方两个 effect）。 */
  const [materialId, setMaterialId] = useState<string>()
  /* 学习模式（P9）：消息级参数，direct=直接答 / guided=引导式；切会话/切课程复位 */
  const [learningMode, setLearningMode] = useState<'direct' | 'guided'>('direct')
  const [scopeMenuOpen, setScopeMenuOpen] = useState(false)
  const [notePickerOpen, setNotePickerOpen] = useState(false)
  const [previewItem, setPreviewItem] = useState<NoteChangeItem>()
  const [scopeLockHint, setScopeLockHint] = useState(false)
  const scopeLockTimer = useRef<number | undefined>(undefined)
  const [webStatus, setWebStatus] = useState<{ configured: boolean; status: string }>({ configured: false, status: 'unconfigured' })
  const [changesOpen, setChangesOpen] = useState(false)
  const [mistakesOpen, setMistakesOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [termOpen, setTermOpen] = useState(false)
  const [railDrawerOpen, setRailDrawerOpen] = useState(false)
  const [pendingInitialQuestion, setPendingInitialQuestion] = useState<string>()
  const [petMode, setPetMode] = useState<PetMode>(() => loadPetPlacement()?.mode ?? 'rail')

  const scope: AskScope = useMemo(
    () => ({ kind: scopeKind, targetId: scopeTargetId, targetTitle: scopeTargetTitle }),
    [scopeKind, scopeTargetId, scopeTargetTitle],
  )

  /* agent 产出的笔记修改建议（P4 多目标）：走课程级待确认端点，
     目标集合 = 本课程的全部 pending（发现开关下 agent 可定位任意笔记提建议）。
     正文缓存种子 = 工作区笔记；未命中的由 hook 按 note_id 拉取。 */
  const noteSuggestions = useNoteSuggestions({
    targets: [],
    knownNotes: notes,
    courseId,
    refreshNotes: refreshCurrentNotes,
    agentFinalId: agentRun?.final?.message_id,
    resetKey: conversation.conversationId,
  })

  /* 答疑页的范围语义 → agent 的请求语义。
     答疑页的「整门课程」= agent 的 course 且不收窄到某份课件（agent 的 course 档可带 material_id）；
     答疑页的「锁定笔记」锁的是用户指定的任意一篇，而 agent 的 note 档强制要求 reading_context.note_id
     （后端 agent.py 会 422），所以要把这篇笔记的正文节选一起带过去。
     发现开关（P4）：只有答疑页传 true——全局/课程档下 agent 也能自主定位笔记提交修改建议。 */
  const agentOptions = useMemo<{ scope: AgentScope; materialId?: string; readingContext?: AgentReadingContext; allowNoteDiscovery: boolean; allowQuiz: boolean; learningMode: 'direct' | 'guided' }>(() => {
    if (scope.kind === 'global') return { scope: 'global', allowNoteDiscovery: true, allowQuiz: true, learningMode }
    if (scope.kind === 'note' && scope.targetId) {
      const note = notes.find((item) => item.id === scope.targetId)
      return {
        scope: 'note',
        readingContext: {
          note_id: scope.targetId,
          note_title: scope.targetTitle ?? note?.title,
          excerpt: note?.content_markdown ? note.content_markdown.slice(0, 1200) : undefined,
        },
        allowNoteDiscovery: true,
        allowQuiz: true,
        learningMode,
      }
    }
    return { scope: 'course', materialId, allowNoteDiscovery: true, allowQuiz: true, learningMode }
  }, [scope.kind, scope.targetId, scope.targetTitle, notes, materialId, learningMode])

  /* 切换会话时，把范围 chip 对齐到该会话的真实归属。
     范围是会话级属性，存在 Conversation 行上；只有「还没有消息」的会话才允许再改。
     用 ref 守门，避免 conversations 列表因别处改名/排序变化时把用户未发送的选择冲掉。 */
  const scopeSyncRef = useRef<string | null>(null)
  useEffect(() => {
    if (scopeSyncRef.current === conversation.conversationId) return
    scopeSyncRef.current = conversation.conversationId ?? null
    const target = conversation.conversationId
      ? conversation.conversations.find((item) => item.id === conversation.conversationId)
      : undefined
    if (!target) {
      // 尚无活动会话（全新对话）→ 默认全局可查
      setScopeKind('global'); setScopeTargetId(undefined); setScopeTargetTitle(undefined); setMaterialId(undefined); setLearningMode('direct')
      return
    }
    setMaterialId(undefined)
    setLearningMode('direct')
    if (target.scope === 'note') {
      setScopeKind('note'); setScopeTargetId(target.note_id ?? undefined); setScopeTargetTitle(target.note_title ?? undefined)
    } else if (target.scope === 'global') {
      setScopeKind('global'); setScopeTargetId(undefined); setScopeTargetTitle(undefined)
    } else {
      setScopeKind('course'); setScopeTargetId(undefined); setScopeTargetTitle(undefined)
    }
  }, [conversation.conversationId, conversation.conversations])

  /* 范围锁定：当前会话一旦有过真实问答（不含本地开场白），就不再允许改范围 */
  const scopeLocked = hasMessages

  function flashScopeLockHint() {
    setScopeLockHint(true)
    if (scopeLockTimer.current) window.clearTimeout(scopeLockTimer.current)
    scopeLockTimer.current = window.setTimeout(() => setScopeLockHint(false), 2600)
  }
  useEffect(() => () => { if (scopeLockTimer.current) window.clearTimeout(scopeLockTimer.current) }, [])

  useEffect(() => {
    setScopeKind('global')
    setScopeTargetId(undefined)
    setScopeTargetTitle(undefined)
    setMaterialId(undefined)
    setLearningMode('direct')
  }, [courseId])

  useEffect(() => { void api.getWebSearchStatus().then(setWebStatus).catch(() => setWebStatus({ configured: false, status: 'unavailable' })) }, [])

  /* 首页「问 AI」带来的问题：等会话就绪后走同一条落库链路 */
  useEffect(() => {
    const state = location.state as { initialQuestion?: unknown } | null
    if (typeof state?.initialQuestion !== 'string' || !state.initialQuestion.trim()) return
    initialQuestionSent.current = false
    setPendingInitialQuestion(state.initialQuestion.trim())
    navigate(location.pathname, { replace: true, state: null })
  }, [location.key, location.pathname, location.state, navigate])

  /* 重试口径快照（v6 P5）：记录每次提问发出时的 agentOptions，重试按原口径重发，
      避免失败到重试之间用户改了范围/收窄导致口径漂移 */
  const recentAsksRef = useRef<Array<{ text: string; options: typeof agentOptions }>>([])

  const send = useCallback((text: string): boolean => {
    const trimmed = text.trim()
    if (!trimmed || busy) return false
    /* 走 agent 流式通道：与悬浮坞同一条能力线（可调工具、正文逐字返回） */
    void askAgent(trimmed, agentOptions).then((sent) => { if (!sent) setDraft(trimmed) })
    recentAsksRef.current = [...recentAsksRef.current.slice(-19), { text: trimmed, options: agentOptions }]
    /* 彩蛋信号：桌宠据此判断"同一句问了两遍"（重试按钮不算） */
    reportQuestion(trimmed)
    return true
  }, [askAgent, busy, agentOptions])

  /* 失败卡重试：优先按提问时的口径快照重发。
     已知限制：后端对重复幂等键直接 409（api/v1/agent.py:61-68），所以这里用新键重发，
     用户会看到两条相同的提问气泡——去重需要后端「按消息 id 重试」的能力，见计划 §7-1。 */
  const retryQuestion = useCallback((text: string) => {
    if (busy) return
    const found = [...recentAsksRef.current].reverse().find((item) => item.text === text)
    const options = found?.options ?? agentOptions
    void askAgent(text, options).then((sent) => { if (!sent) setDraft(text) })
  }, [askAgent, busy, agentOptions])

  /* 错题本两个动作（v6 §7 第一批）：意图明确，直接走发送通道；
     send 在忙碌时返回 false，此时退化为填草稿并聚焦输入框，不丢用户操作。 */
  const askFromMistake = useCallback((prompt: string) => {
    setMistakesOpen(false)
    if (!send(prompt)) {
      setDraft(prompt)
      composerRef.current?.focus()
    }
  }, [send])

  useEffect(() => {
    if (!pendingInitialQuestion || !ready || initialQuestionSent.current) return
    const text = pendingInitialQuestion
    initialQuestionSent.current = true
    setPendingInitialQuestion(undefined)
    send(text)
  }, [pendingInitialQuestion, ready, send])

  /* Ctrl/Cmd+K 唤起会话搜索 */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  /* 滚动条显隐：滑动中或鼠标悬停时显示滑块（恒定 8px 透明沟槽，只切滑块颜色，不引发回流）。
     - scroll：加 .is-scrolling 并重置 650ms 隐藏计时；
     - 悬停：pointerover 加 .is-scrolling；pointerout 离开且无进行中的滚动计时则移除；
     - 隐藏计时到点若仍在悬停则不隐藏（悬停期间保持可见）。
     实测纯 CSS :hover 不会重绘滚动条滑块，故悬停也走加 class 这条可靠路径。
     每个滚动区用 WeakMap 独立计时，避免多容器互相覆盖导致某个不消失。 */
  useEffect(() => {
    const SCROLL_SEL = '.workspace-rail-scroll, .workspace-thread, .workspace-changes-list, .workspace-palette-list, .workspace-scope-picker-list'
    const timers = new WeakMap<HTMLElement, number>()
    const scrollerFrom = (node: EventTarget | null): HTMLElement | null => {
      if (!(node instanceof Element)) return null
      const el = node.closest(SCROLL_SEL)
      return el instanceof HTMLElement ? el : null
    }
    const onScroll = (event: Event) => {
      const el = event.target
      if (!(el instanceof HTMLElement) || el === document.body) return
      el.classList.add('is-scrolling')
      const pending = timers.get(el)
      if (pending) window.clearTimeout(pending)
      timers.set(el, window.setTimeout(() => {
        timers.delete(el)
        if (!el.matches(':hover')) el.classList.remove('is-scrolling')
      }, 650))
    }
    const onOver = (event: Event) => {
      const el = scrollerFrom(event.target)
      if (el) el.classList.add('is-scrolling')
    }
    const onOut = (event: Event) => {
      const el = scrollerFrom(event.target)
      if (!el) return
      const related = (event as PointerEvent).relatedTarget
      if (related instanceof Node && el.contains(related)) return
      if (!timers.has(el)) el.classList.remove('is-scrolling')
    }
    document.addEventListener('scroll', onScroll, true)
    document.addEventListener('pointerover', onOver)
    document.addEventListener('pointerout', onOut)
    return () => {
      document.removeEventListener('scroll', onScroll, true)
      document.removeEventListener('pointerover', onOver)
      document.removeEventListener('pointerout', onOut)
    }
  }, [])

  function changeScope(next: ScopeNext) {
    /* 已锁定的会话不再接受范围变更（UI 层拦截；后端也只在首轮落 scope，双保险） */
    if (scopeLocked) { flashScopeLockHint(); return }
    setScopeKind(next.kind)
    setScopeTargetId(next.targetId)
    setScopeTargetTitle(next.targetTitle)
    /* 收窄只在 course 档有意义：离开该档即复位，避免残留一个不可见的消息级参数 */
    if (next.kind !== 'course') setMaterialId(undefined)
  }

  function changePetMode(mode: PetMode) {
    setPetMode(mode)
    const placement = loadPetPlacement()
    savePetPlacement({
      version: 1,
      mode,
      xRatio: placement?.xRatio ?? 0.82,
      yRatio: placement?.yRatio ?? 0.62,
    })
  }

  function useStarter(prompt: string) {
    setDraft(prompt)
    composerRef.current?.focus()
  }

  async function handleFeedback(messageId: string, category: 'helpful' | 'not_helpful', comment?: string): Promise<boolean> {
    if (!courseId) return false
    try {
      await api.saveFeedback(courseId, { target_type: 'assistant_message', target_id: messageId, category, comment })
      return true
    } catch {
      return false
    }
  }

  function openMaterial(materialId: string, page?: number) {
    openMaterialSource(materialId, page)
    if (courseId) navigate(featurePath(courseId, 'materials'))
  }

  const persona = teacherPersonaMeta()
  const lastAssistantMessage = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant'),
    [messages],
  )
  const hasAsked = messages.some((message) => message.role === 'user')
  const teacherStatus: TeacherStatus = busy
    ? 'thinking'
    : lastAssistantMessage?.status === 'failed' ? 'error'
      : hasAsked ? 'explaining' : 'idle'
  const statusCopy = busy
    ? '正在翻课程资料…'
    : lastAssistantMessage?.status === 'failed' ? '刚才没答上来，可以再试一次'
      : hasAsked ? '刚回答完，角标可以点开原文' : '等待你的问题'

  /* 能力行（WorkBuddy 式）：任务类 chips 常驻输入框上方，功能可发现不靠话术 */
  const quickPrompts = materials.length
    ? [
      { label: '考考我', prompt: '考考我：针对这一讲出两道题。' },
      { label: '复习提纲', prompt: '帮我把这一讲整理成复习提纲。' },
      { label: '易混概念', prompt: '这一讲有哪些容易混淆的概念？请对比说明。' },
    ]
    : []

  const starterPrompts = materials.length
    ? [
      '这门课最重要的三个概念是什么？',
      '用一句话解释这一讲的核心定义。',
      '帮我把这一讲整理成复习提纲。',
    ]
    : [
      '这门课可以按什么顺序学？',
      '帮我列出这门课需要先掌握的基础。',
      '我该怎么开始整理第一份课件？',
    ]

  const scopeLabel = scopeKind === 'global'
    ? '全局可查'
    : scopeKind === 'note'
      ? (scopeTargetTitle ?? '锁定笔记')
      : '整门课程'

  const retrievalSummary = useMemo(() => {
    const sources = lastAssistantMessage?.sources ?? []
    if (sources.length === 0) return null
    return {
      materials: new Set(sources.map((source) => source.material_id).filter(Boolean)).size,
      items: sources.length,
    }
  }, [lastAssistantMessage])

  return (
    <div className="feature-page page-enter assistant-page workspace-pet">
      <h1 className="workspace-sr-only">答疑桌宠</h1>

      <aside className={`workspace-rail${railDrawerOpen ? ' is-drawer-open' : ''}`} aria-label="桌宠与会话">
        <div className="workspace-rail-head">
          <span className="eyebrow">DESK PET · 桌宠</span>
        </div>

        {/* PetAvatar 必须常挂载：浮层是它内部的 portal，放进条件分支会在切形态时连人一起卸载 */}
        <div className={`workspace-pet-block${petMode === 'float' ? ' is-floating' : ''}`}>
          <PetAvatar
            mode={petMode}
            onModeChange={changePetMode}
            status={teacherStatus}
            /* 只认「本次请求已开始吐正文」：工具阶段/思考阶段都还在 thinking */
            streaming={busy && (agentRun?.streamingText.length ?? 0) > 0}
            draft={draft}
            bubbleHint={busy ? '正在翻课程资料，稍等一下…' : hasAsked ? '回答里的角标可以点，右栏能看到原文。' : `问我「${course?.name ?? '这门课'}」的问题吧`}
          />
          {petMode === 'rail' && (
            <div className="workspace-pet-identity">
              <span className="workspace-pet-identity-avatar" aria-hidden="true">
                <TeacherCharacter status={teacherStatus} compact />
              </span>
              <div className="workspace-pet-identity-text">
                <h2>{persona.name}</h2>
                <p>{persona.title} · 教学助手</p>
              </div>
              <div className="workspace-pet-identity-foot">
                <span className={`workspace-pet-status${busy ? ' is-busy' : ''}`} role="status" aria-live="polite">
                  <i aria-hidden="true" />{statusCopy}
                </span>
                <button
                  type="button"
                  className="workspace-pet-floatout"
                  onClick={() => changePetMode('float')}
                  title="让桌宠浮到页面上，可任意拖动"
                >浮出 ⤢</button>
              </div>
            </div>
          )}
        </div>

        {petMode === 'float' && (
          <div className="workspace-pet-anchor">
            <span className="workspace-pet-anchor-avatar" aria-hidden="true">
              <TeacherCharacter status={teacherStatus} compact />
            </span>
            <div className="workspace-pet-anchor-text">
              <strong>{persona.name}</strong>
              <span>{busy ? '浮层里待命中' : '在页面上，可随时拖动'}</span>
            </div>
            <button
              type="button"
              className="workspace-pet-anchor-recall"
              onClick={() => changePetMode('rail')}
              title="把桌宠召回左栏（双击浮层或按 Home 也可以）"
            >召回 <span aria-hidden="true">←</span></button>
          </div>
        )}

        <div className="workspace-rail-scroll">
          <div className="workspace-conv-head">
            <span className="workspace-mini-label">会话</span>
            <button
              type="button"
              className="workspace-conv-new"
              disabled={busy || !courseId}
              onClick={() => {
                /* 新对话一律从「全局可查」重新开始，不继承上一段的选择 */
                changeScope({ kind: 'global' })
                void conversation.startNewConversation({ scope: 'global' })
              }}
            >＋ 新对话</button>
          </div>
          <ConversationList
            conversations={conversation.conversations}
            courses={courses}
            conversationId={conversation.conversationId}
            busy={busy}
            error={conversation.error}
            onSelect={(id) => { setRailDrawerOpen(false); void conversation.selectConversation(id) }}
            onRename={(id, title) => conversation.renameConversation(id, title)}
            onDelete={(id) => conversation.deleteConversation(id)}
          />
        </div>
      </aside>

      {railDrawerOpen && (
        <div className="workspace-rail-backdrop is-open" onClick={() => setRailDrawerOpen(false)} aria-hidden="true" />
      )}

      <section className="workspace-chat" aria-label="课程答疑对话">
        <header className="workspace-topbar">
          <h2 className="workspace-title">答疑桌宠 <span>· {course?.name ?? '当前课程'}</span></h2>
          <div className="workspace-topbar-actions">
            <button
              type="button"
              className="workspace-topbar-conv-toggle"
              onClick={() => setRailDrawerOpen(true)}
              aria-label="打开会话列表"
            >会话</button>
            <button
              type="button"
              className="workspace-topbar-search"
              onClick={() => setPaletteOpen(true)}
              title="搜索会话（Ctrl+K）"
              aria-label="搜索会话"
            >⌕</button>
            <button
              type="button"
              className="workspace-topbar-mistakes"
              onClick={() => setMistakesOpen(true)}
              title="错题本 · 本课程答错的题"
              aria-label="打开错题本"
            >复习</button>
            <button
              type="button"
              className="workspace-topbar-changes"
              onClick={() => setChangesOpen((open) => !open)}
              aria-pressed={changesOpen}
              title={changesOpen ? '收起改动栏' : '展开改动栏'}
              aria-label={changesOpen ? '收起改动栏' : '展开改动栏'}
            >改动</button>
            <button
              type="button"
              className="primary-button workspace-topbar-new"
              disabled={busy || !courseId}
              onClick={() => {
                changeScope({ kind: 'global' })
                void conversation.startNewConversation({ scope: 'global' })
              }}
            >＋ 新对话</button>
          </div>
        </header>

        <AssistantContextBar
          courses={courses}
          scopeKind={scopeKind}
          scopeTargetId={scopeTargetId}
          scopeTargetTitle={scopeTargetTitle}
          onScopeChange={changeScope}
          onOpenNotePicker={() => {
            setScopeMenuOpen(false)
            setNotePickerOpen(true)
          }}
          onSelectCourse={(id) => {
            /* 选当前课程 = 把范围落到「整门课程」；选别的课程 = 跳到那门课的上下文 */
            if (id === courseId) changeScope({ kind: 'course' })
            else navigate(featurePath(id, 'assistant'))
            setScopeMenuOpen(false)
          }}
          summary={retrievalSummary}          scopeMenuOpen={scopeMenuOpen}
          onScopeMenuChange={setScopeMenuOpen}
          locked={scopeLocked}
          lockHint={scopeLockHint}
          onLockedAttempt={flashScopeLockHint}
        />

        <AssistantThread
          ready={ready}
          busy={busy}
          messages={messages}
          conversationId={conversation.conversationId}
          personaName={persona.name}
          starters={starterPrompts}
          onStarter={useStarter}
          onFeedback={handleFeedback}
          onOpenMaterial={openMaterial}
          onRetry={retryQuestion}
          onFollowUp={useStarter}
          agentRun={agentRun}
          suggestionsByMessage={conversation.agentSuggestionsByMessage}
          skillCourseId={courseId}
          onSkillAsk={useStarter}
          highlightMessageId={conversation.pendingMessageId}
          onHighlightConsumed={conversation.consumePendingMessage}
          extras={(
            <>
              <NoteSuggestionCards
                suggestions={noteSuggestions.suggestions}
                currentContentByNoteId={noteSuggestions.contentById}
                busyId={noteSuggestions.busyId}
                adoptedContents={noteSuggestions.adopted}
                onReview={(suggestion, decision, finalMarkdown) => void noteSuggestions.review(suggestion, decision, finalMarkdown)}
                onUndo={(suggestion) => void noteSuggestions.undo(suggestion)}
              />
              {noteSuggestions.notice ? <p className="workspace-agent-notice">{noteSuggestions.notice}</p> : null}
            </>
          )}
        />

        <div className="workspace-chat-foot" ref={composerAreaRef}>
          {conversation.error && <p className="workspace-error" role="alert">{conversation.error}</p>}
          {courseContentLoading ? (
            <p className="workspace-inline-status" role="status">正在读取课程资料…</p>
          ) : materials.length === 0 && (
            <div className="workspace-no-materials">
              <span>这门课还没有可检索的资料。上传并解析课件后，回答才会引用课程内容。</span>
              {courseId && <Link to={featurePath(courseId, 'materials')}>去上传课程资料 <span aria-hidden="true">→</span></Link>}
            </div>
          )}
          <AssistantComposer
            draft={draft}
            onDraftChange={setDraft}
            onSubmit={send}
            busy={busy}
            onStop={() => stopAgent()}
            placeholder={`问${persona.name}任何关于「${course?.name ?? '当前课程'}」的问题……`}
            hint={`Enter 发送 · Shift+Enter 换行 · ${webStatus.configured ? '网络补充单独标注' : '只检索当前课程'}`}
            scopeLabel={scopeLabel}
            onScopeClick={() => setScopeMenuOpen((open) => !open)}
            onTermClick={() => setTermOpen(true)}
            onComposerFocus={() => petRef.current?.yieldFromRect(composerAreaRef.current?.getBoundingClientRect() ?? null)}
            textareaRef={composerRef}
            materials={scopeKind === 'course'
              ? materials.filter((item) => item.status === 'completed').map((item) => ({ id: item.id, lecture_title: item.lecture_title }))
              : undefined}
            materialId={materialId}
            onMaterialChange={setMaterialId}
            learningMode={learningMode}
            onLearningModeChange={setLearningMode}
            quickPrompts={quickPrompts}
            onQuickPrompt={useStarter}
          />
        </div>
      </section>

      <ChangesPanel
        open={changesOpen}
        onToggle={() => setChangesOpen((open) => !open)}
        items={noteSuggestions.changes}
        /* 只把已解析完成的课件传下去，正在解析的还没页数，列出来只会误导 */
        materials={materials.filter((item) => item.status === 'completed')}
        onApplyAll={() => void noteSuggestions.applyAll()}
        applying={noteSuggestions.busyId === '__all__'}
        onPreview={(item) => setPreviewItem(item)}
      />

      <MistakeBook
        open={mistakesOpen}
        courseId={courseId}
        courseName={course?.name}
        onClose={() => setMistakesOpen(false)}
        onExplain={askFromMistake}
        onRetry={askFromMistake}
      />

      <NotePreviewDialog
        open={Boolean(previewItem)}
        title={previewItem?.noteTitle ?? ''}
        chapter={previewItem?.chapter}
        /* 多目标：预览的「当前正文」按预览项自己的目标笔记取 */
        current={previewItem ? (noteSuggestions.contentById[previewItem.noteId] ?? '') : ''}
        proposed={previewItem?.proposed ?? ''}
        onClose={() => setPreviewItem(undefined)}
      />

      {paletteOpen && (
        <ConversationSearch
          conversations={conversation.conversations}
          conversationId={conversation.conversationId}
          courseId={courseId}
          onSelect={(id) => void conversation.selectConversation(id)}
          onSelectMessage={(conversationId, messageId) => {
            /* P6 消息命中：切会话时带上定位目标，历史加载完由线程滚动高亮 */
            void conversation.selectConversation(conversationId, messageId)
          }}
          onClose={() => setPaletteOpen(false)}
        />
      )}
      <TermDialog open={termOpen} onClose={() => setTermOpen(false)} courseId={courseId} />

      <NoteScopePicker
        open={notePickerOpen}
        courses={courses}
        currentCourseId={courseId}
        currentNotes={notes}
        loadNotes={(id) => api.listNotes(id)}
        onPick={(note) => {
          changeScope({ kind: 'note', targetId: note.id, targetTitle: note.title })
          setNotePickerOpen(false)
        }}
        onClose={() => setNotePickerOpen(false)}
      />
    </div>
  )
}
