import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../api'
import type { ConversationOwnership } from '../../api/conversations'
import { streamAgentMessage, type AgentDeltaEvent, type AgentErrorEvent, type AgentFinalEvent, type AgentNoticeEvent, type AgentNotebookContext, type AgentReadingContext, type AgentScope, type AgentStepEvent, type AgentThinkingEvent } from '../../api/agent'
import type { TeacherCharacterId } from '../../components/TeacherCharacter'
import type { Conversation, ConversationMessage } from '../../types'
import { teacherPersonaMeta } from '../persona/personas'

/**
 * 答疑的唯一状态源。
 *
 * 首页「问 AI」、答疑页、悬浮答疑坞三个入口都读写这一份会话，
 * 提问统一走 POST /conversations/{id}/messages（落库 + 历史 + 来源），
 * 不再保留只存内存的第二条链路。
 *
 * 悬浮坞的 agent 模式走 ``askAgent``（SSE 流式端点）：旧 ``ask`` 保留不动，
 * 最终回答同样规范成 ConversationMessage 追加入历史，三入口依然共享同一份历史。
 */

export type AskScope = {
  /** 会话归属：全局可查 / 整门课程 / 锁定笔记 */
  kind?: 'global' | 'course' | 'note'
  /** 锁定笔记时的笔记 id（kind === 'note'） */
  targetId?: string
  /** 锁定笔记时的笔记标题，用于历史分组与标签 */
  targetTitle?: string
}

/** agent 执行中的实时状态：步骤时间线 + 流式文本 + 最终事件 */
export type AgentRunState = {
  steps: AgentStepEvent[]
  /** 思维链累计文本（所有轮次拼接）；仅展示用，随 final 的 process 落库 */
  thinking: string
  streamingText: string
  notice?: string
  final?: AgentFinalEvent
  /** 用户主动中断：保留已收到的正文，实时块改渲染成「已中断」而不是一直「执行中」 */
  aborted?: boolean
}

export type AgentAskOptions = {
  scope: AgentScope
  materialId?: string
  readingContext?: AgentReadingContext
  notebookContext?: AgentNotebookContext
  allowQuiz?: boolean
  learningMode?: 'direct' | 'guided'
}

export type ConversationState = {
  conversations: Conversation[]
  conversationId?: string
  /** 可直接渲染的消息列表；会话为空时给当前老师的开场白（本地注入，不入库） */
  messages: ConversationMessage[]
  /** 会话是否已有真实问答（不含本地开场白）。范围锁定等「是否已开始对话」的判断用这个，
      不能用 messages——空会话会被注入开场白而恒为非空 */
  hasMessages: boolean
  busy: boolean
  /** 会话与历史是否已就绪。首条问题宜等到就绪，避免与建会话竞态 */
  ready: boolean
  error?: string
  /** agent 执行中的实时状态；非 agent 提问时为 null */
  agentRun: AgentRunState | null
  /** 搜索命中消息带来的定位目标：历史加载完后由线程滚动高亮，消费后清除 */
  pendingMessageId?: string
  /** 打开会话；传 pendingMessageId 表示要定位到该条消息 */
  selectConversation: (id: string, pendingMessageId?: string) => Promise<void>
  /** 线程完成定位高亮后调用，清掉定位目标 */
  consumePendingMessage: () => void
  /** 重命名会话（右键菜单）；成功更新本地列表标题，返回是否成功 */
  renameConversation: (id: string, title: string) => Promise<boolean>
  /** 删除整段会话（右键菜单）；删的是当前会话时切换到剩余最近一条，或清空等待下次新建 */
  deleteConversation: (id: string) => Promise<boolean>
  /** 开一段新对话（悬浮坞的「新建对话」）。后端没有删除接口，所以用新建代替清空 */
  startNewConversation: (ownership?: ConversationOwnership) => Promise<void>
  /** 发送提问；返回 false 表示未发出（调用方可把文本还回输入框） */
  ask: (text: string, scope?: AskScope) => Promise<boolean>
  /** agent 流式提问（悬浮坞专用）；成功把回答追加入历史时返回 true */
  askAgent: (text: string, options: AgentAskOptions) => Promise<boolean>
  /** 中断正在进行的 agent 回答：中止本次请求，保留已收到的正文（标记「已中断」） */
  stopAgent: () => void
}

function greetingMessage(conversationId: string | undefined, content: string): ConversationMessage {
  return {
    id: 'local-greeting',
    conversation_id: conversationId ?? '',
    role: 'assistant',
    content,
    learning_goal: null,
    status: 'completed',
    model_version: null,
    failure_type: null,
    created_at: '',
    evidence: [],
    mode: null,
    sources: [],
  }
}

export function useConversation(
  courseId?: string,
  teacherPersona: TeacherCharacterId = 'elf',
): ConversationState {
  const courseRef = useRef(courseId)
  courseRef.current = courseId
  const greeting = teacherPersonaMeta(teacherPersona).greeting

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<string>()
  const [history, setHistory] = useState<ConversationMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string>()
  const [agentRun, setAgentRun] = useState<AgentRunState | null>(null)
  /** 搜索命中的定位目标：历史加载完后由线程滚动高亮，消费后清除 */
  const [pendingMessageId, setPendingMessageId] = useState<string>()
  const busyRef = useRef(false)
  const creatingRef = useRef<Promise<string> | null>(null)
  const historyRequestRef = useRef(0)
  /** 当前 agent 请求的中断器：用户点「停止」时 abort 掉它 */
  const abortRef = useRef<AbortController | null>(null)

  /** fetch 被 abort 时抛的是 AbortError（DOMException）；部分实现把它包在 cause 里 */
  function isAbortError(cause: unknown): boolean {
    if (!cause || typeof cause !== 'object') return false
    if ((cause as { name?: unknown }).name === 'AbortError') return true
    const inner = (cause as { cause?: unknown }).cause
    return Boolean(inner && typeof inner === 'object' && (inner as { name?: unknown }).name === 'AbortError')
  }

  /* 切换课程：重建会话上下文。空课程建立首个会话，保证后续提问总有落点 */
  useEffect(() => {
    let active = true
    const request = ++historyRequestRef.current
    setConversations([])
    setConversationId(undefined)
    setHistory([])
    setError(undefined)
    setAgentRun(null)
    setReady(false)
    creatingRef.current = null
    if (!courseId) {
      setReady(true)
      return () => { active = false }
    }
    void api.listConversations(courseId).then(async (items) => {
      /* 课程没有历史时先建一段空会话；范围默认「全局可查」，用户可在首条消息前改 */
      const next = items.length > 0 ? items : [await api.createConversation(courseId, '新对话', { scope: 'global' })]
      if (!active || historyRequestRef.current !== request) return
      setConversations(next)
      setConversationId(next[0].id)
      const loaded = await api.listConversationMessages(next[0].id)
      if (!active || historyRequestRef.current !== request) return
      setHistory(loaded)
      setReady(true)
    }).catch((cause: unknown) => {
      if (!active || historyRequestRef.current !== request) return
      setError(cause instanceof Error ? cause.message : '会话读取失败')
      setReady(true)
    })
    return () => { active = false }
  }, [courseId])

  const selectConversation = useCallback(async (id: string, pendingMessageId?: string) => {
    const request = ++historyRequestRef.current
    const requestCourseId = courseRef.current
    setConversationId(id)
    /* 带消息命中的跳转记录定位目标；普通切换传 undefined 顺带清掉遗留目标 */
    setPendingMessageId(pendingMessageId)
    setHistory([])
    setBusy(true)
    setError(undefined)
    try {
      const loaded = await api.listConversationMessages(id)
      if (historyRequestRef.current === request && courseRef.current === requestCourseId) setHistory(loaded)
    } catch (cause) {
      if (historyRequestRef.current === request && courseRef.current === requestCourseId) {
        setError(cause instanceof Error ? cause.message : '会话读取失败')
      }
    } finally {
      if (historyRequestRef.current === request && courseRef.current === requestCourseId) {
        setBusy(false)
        setReady(true)
      }
    }
  }, [])

  /* 线程完成滚动高亮后消费定位目标 */
  const consumePendingMessage = useCallback(() => setPendingMessageId(undefined), [])

  const renameConversation = useCallback(async (id: string, title: string): Promise<boolean> => {
    const trimmed = title.trim()
    if (!trimmed) return false
    try {
      const updated = await api.renameConversation(id, trimmed)
      if (courseRef.current === courseId) {
        setConversations((current) => current.map((item) => (item.id === id ? { ...item, title: updated.title } : item)))
      }
      return true
    } catch (cause) {
      if (courseRef.current === courseId) setError(cause instanceof Error ? cause.message : '重命名失败')
      return false
    }
  }, [courseId])

  const deleteConversation = useCallback(async (id: string): Promise<boolean> => {
    const requestCourseId = courseId
    if (!requestCourseId) return false
    try {
      await api.deleteConversation(id)
      if (courseRef.current !== requestCourseId) return true
      setConversations((current) => current.filter((item) => item.id !== id))
      // 删的是当前会话：切到剩余最近一条，或清空（下次提问时 ensureConversation 会新建）
      if (id === conversationId) {
        const remaining = conversations.filter((item) => item.id !== id)
        if (remaining.length > 0) await selectConversation(remaining[0].id)
        else { setConversationId(undefined); setHistory([]) }
      }
      return true
    } catch (cause) {
      if (courseRef.current === requestCourseId) setError(cause instanceof Error ? cause.message : '删除失败')
      return false
    }
  }, [courseId, conversationId, conversations, selectConversation])

  /* 悬浮坞的「新建对话」：后端只有会话级接口，没有单条消息删除，
     因此「清空」等价于开一段新会话，旧会话仍可在答疑页的历史里找回 */
  const startNewConversation = useCallback(async (ownership?: ConversationOwnership): Promise<void> => {
    const requestCourseId = courseId
    if (!requestCourseId || busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError(undefined)
    try {
      const created = await api.createConversation(requestCourseId, '新对话', ownership)
      if (courseRef.current !== requestCourseId) return
      historyRequestRef.current += 1
      setConversations((current) => [created, ...current.filter((item) => item.id !== created.id)])
      setConversationId(created.id)
      setHistory([])
    } catch (cause) {
      if (courseRef.current === requestCourseId) {
        setError(cause instanceof Error ? cause.message : '新建对话失败')
      }
    } finally {
      busyRef.current = false
      if (courseRef.current === requestCourseId) setBusy(false)
    }
  }, [courseId])

  /* 会话尚未建立就发问时补建一个（悬浮坞可能在异步建会话完成前就提交） */
  const ensureConversation = useCallback(async (ownership?: ConversationOwnership): Promise<string | undefined> => {
    if (!courseId) return undefined
    if (conversationId) return conversationId
    if (creatingRef.current) return creatingRef.current
    const pending = api.createConversation(courseId, '新对话', ownership).then((created) => {
      if (courseRef.current === courseId) {
        setConversations((current) => [created, ...current.filter((item) => item.id !== created.id)])
        setConversationId(created.id)
      }
      creatingRef.current = null
      return created.id
    }).catch((cause: unknown) => {
      creatingRef.current = null
      throw cause
    })
    creatingRef.current = pending
    return pending
  }, [courseId, conversationId])

  const ask = useCallback(async (text: string, scope: AskScope = {}): Promise<boolean> => {
    const question = text.trim()
    const requestCourseId = courseId
    if (!requestCourseId || !question || busyRef.current) return false
    const firstTurn = !history.some((message) => message.role === 'user')
    busyRef.current = true
    setBusy(true)
    setError(undefined)
    /* 范围是会话级属性：建会话时定，首条消息落库，之后锁定。
       course 也显式传，避免与「未指定」混淆（未指定时由调用方决定默认值）。 */
    const ownership = scope.kind === 'global'
      ? { scope: 'global' as const }
      : scope.kind === 'note'
        ? { scope: 'note' as const, noteId: scope.targetId ?? null, noteTitle: scope.targetTitle ?? null }
        : { scope: 'course' as const }
    try {
      const targetId = await ensureConversation(ownership)
      if (!targetId || courseRef.current !== requestCourseId) return false
      const askedAt = Date.now()
      setHistory((current) => [...current, {
        id: `local-user-${askedAt}`,
        conversation_id: targetId,
        role: 'user',
        content: question,
        learning_goal: null,
        status: 'completed',
        model_version: null,
        failure_type: null,
        created_at: new Date(askedAt).toISOString(),
        evidence: [],
        mode: null,
        sources: [],
      }])
      const answer = await api.sendConversationMessage(targetId, {
        question,
        teacher_persona: teacherPersona,
        /* 刻意不传 learning_goal：留空后由后端 discipline.infer_context 按问题关键词
           推断（怎么做→解决练习、区别→比较方法…）。此前界面恒定发送「理解概念」，
           会把这条推断分支短路掉，反而更差。 */
        allow_web: true,
        scope: ownership?.scope,
        note_id: ownership?.noteId ?? null,
        note_title: ownership?.noteTitle ?? null,
        idempotency_key: `${targetId}-${askedAt}`,
      })
      if (courseRef.current !== requestCourseId) return true
      setHistory((current) => [...current, answer])
      // 首条问题后端已把标题从「新对话」改写；据此刷新历史列表。
      // 归属（scope/note 快照）只在首轮生效，故按本次发送的范围同步列表字段；
      // 后续轮次不得按调用方参数改写已经锁定的归属。
      if (firstTurn || answer.conversation_title) {
        setConversations((current) => current.map((item) => {
          if (item.id !== targetId) return item
          const next = { ...item, title: answer.conversation_title ?? item.title }
          if (firstTurn && ownership?.scope) {
            next.scope = ownership.scope
            next.default_scope = ownership.scope
            next.note_id = ownership.scope === 'note' ? (ownership.noteId ?? null) : null
            next.note_title = ownership.scope === 'note' ? (ownership.noteTitle ?? null) : null
          }
          return next
        }))
      }
      return true
    } catch (cause) {
      if (courseRef.current === requestCourseId) {
        setError(cause instanceof Error ? cause.message : '问答请求失败')
      }
      return false
    } finally {
      busyRef.current = false
      if (courseRef.current === requestCourseId) setBusy(false)
    }
  }, [courseId, teacherPersona, ensureConversation, history])

  /* agent 流式提问：本地插入用户消息 → 逐步更新 agentRun → final 规范成消息入历史 */
  const askAgent = useCallback(async (text: string, options: AgentAskOptions): Promise<boolean> => {
    const question = text.trim()
    const requestCourseId = courseId
    if (!requestCourseId || !question || busyRef.current) return false
    busyRef.current = true
    setBusy(true)
    setError(undefined)
    setAgentRun({ steps: [], thinking: '', streamingText: '' })
    let targetId = ''
    const historyRequest = historyRequestRef.current
    const firstTurn = !history.some((message) => message.role === 'user')
    const isCurrentRequest = () => courseRef.current === requestCourseId
      && historyRequestRef.current === historyRequest
    let ownershipSynced = false
    const acceptOwnership = (title?: string) => {
      if (!isCurrentRequest() || (ownershipSynced && !title)) return
      ownershipSynced = true
      // Any SSE event proves the backend accepted and persisted the question.
      // Its first-turn scope is locked before streaming starts, even if the
      // model fails or the user stops before receiving a final event.
      setConversations((current) => current.map((item) => item.id !== targetId ? item : {
        ...item,
        ...(title ? { title } : {}),
        ...(firstTurn ? {
          scope: options.scope,
          default_scope: options.scope,
          note_id: options.scope === 'note' ? options.notebookContext?.notebook_id ?? null : null,
          note_title: options.scope === 'note'
            ? options.notebookContext?.title ?? options.readingContext?.note_title ?? item.note_title
            : null,
        } : {}),
      }))
    }
    const refreshSavedConversation = async (reloadHistory: boolean) => {
      if (!targetId || !isCurrentRequest()) return
      const [savedConversations, savedMessages] = await Promise.allSettled([
        api.listConversations(requestCourseId),
        reloadHistory ? api.listConversationMessages(targetId) : Promise.resolve(undefined),
      ])
      if (!isCurrentRequest()) return
      if (savedConversations.status === 'fulfilled') {
        const saved = savedConversations.value.find((item) => item.id === targetId)
        if (saved) setConversations((current) => current.map((item) => item.id === targetId ? saved : item))
      }
      if (savedMessages.status === 'fulfilled' && savedMessages.value) setHistory(savedMessages.value)
    }
    /* 中断器：用户点「停止」时 abort 本次请求（signal 铺在 fetch 上，见 api/agent.ts） */
    const controller = new AbortController()
    abortRef.current = controller
    try {
      targetId = await ensureConversation() ?? ''
      if (!targetId || courseRef.current !== requestCourseId) return false
      const askedAt = Date.now()
      setHistory((current) => [...current, {
        id: `local-user-${askedAt}`,
        conversation_id: targetId,
        role: 'user',
        content: question,
        learning_goal: null,
        status: 'completed',
        model_version: null,
        failure_type: null,
        created_at: new Date(askedAt).toISOString(),
        evidence: [],
        mode: null,
        sources: [],
      }])
      await streamAgentMessage(targetId, {
        question,
        scope: options.scope,
        teacher_persona: teacherPersona,
        material_id: options.materialId,
        allow_web: true,
        allow_quiz: options.allowQuiz ?? true,
        learning_mode: options.learningMode ?? 'direct',
        idempotency_key: `${targetId}-${askedAt}`,
        reading_context: options.readingContext,
        notebook_context: options.notebookContext,
      }, {
        onStep: (event: AgentStepEvent) => {
          if (!isCurrentRequest()) return
          acceptOwnership()
          setAgentRun((current) => current ? { ...current, steps: [...current.steps, event] } : current)
        },
        /* 思考增量保留远端字符串契约；范围同步和旧请求隔离与其他事件一致。 */
        onThinking: (event: AgentThinkingEvent) => {
          if (!isCurrentRequest()) return
          acceptOwnership()
          setAgentRun((current) => current ? { ...current, thinking: current.thinking + event.text } : current)
        },
        onDelta: (event: AgentDeltaEvent) => {
          if (!isCurrentRequest()) return
          acceptOwnership()
          setAgentRun((current) => current ? { ...current, streamingText: current.streamingText + event.text } : current)
        },
        onNotice: (event: AgentNoticeEvent) => {
          if (!isCurrentRequest()) return
          acceptOwnership()
          setAgentRun((current) => current ? { ...current, notice: event.text } : current)
        },
        onError: (event: AgentErrorEvent) => {
          if (!isCurrentRequest()) return
          acceptOwnership()
          setError(event.message)
        },
        onFinal: (final: AgentFinalEvent) => {
          if (courseRef.current !== requestCourseId || historyRequestRef.current !== historyRequest) return
          setAgentRun((current) => current ? { ...current, final } : current)
          setHistory((current) => [...current, {
            id: final.message_id ?? `local-agent-${askedAt}`,
            conversation_id: targetId,
            role: 'assistant',
            content: final.answer,
            learning_goal: null,
            status: 'completed',
            model_version: final.model_version ?? null,
            failure_type: null,
            created_at: new Date().toISOString(),
            evidence: [],
            mode: final.mode,
            sources: final.sources ?? [],
            suggestions: final.suggestions ?? [],
            process: final.process ?? null,
          }])
          acceptOwnership(final.conversation_title)
        },
      }, controller.signal)
      await refreshSavedConversation(true)
      return true
    } catch (cause) {
      /* 用户中断：不是错误。保留已收到的正文并打「已中断」标记；
         不弹错误、不重载消息历史；只刷新会话归属，保留已收到的本地正文。 */
      if (isAbortError(cause)) {
        if (courseRef.current === requestCourseId && historyRequestRef.current === historyRequest) {
          setAgentRun((current) => current ? { ...current, aborted: true } : current)
        }
        await refreshSavedConversation(false)
        return true
      }
      if (courseRef.current === requestCourseId && historyRequestRef.current === historyRequest) {
        setError(cause instanceof Error ? cause.message : '智能问答请求失败')
        setAgentRun(null)
        await refreshSavedConversation(true)
      }
      return false
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      busyRef.current = false
      if (courseRef.current === requestCourseId) setBusy(false)
    }
  }, [courseId, teacherPersona, ensureConversation, history])

  /* 中断正在进行的回答：abort 当前请求，已收到的正文保留（实时块改渲染成「已中断」） */
  const stopAgent = useCallback(() => {
    const controller = abortRef.current
    if (!controller) return
    controller.abort()
    setAgentRun((current) => current ? { ...current, aborted: true } : current)
  }, [])

  /* 会话为空时由前端补一条开场白（不入库）；已有历史则原样展示。
     注意：messages 因此永远非空，判断「会话是否已有真实问答」必须用 hasMessages。 */
  const messages = useMemo(
    () => (history.length > 0 ? history : [greetingMessage(conversationId, greeting)]),
    [history, conversationId, greeting],
  )

  return { conversations, conversationId, messages, hasMessages: history.length > 0, busy, ready, error, agentRun, pendingMessageId, selectConversation, consumePendingMessage, renameConversation, deleteConversation, startNewConversation, ask, askAgent, stopAgent }
}
