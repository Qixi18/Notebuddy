import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../api'
import type { TeacherCharacterId } from '../../components/TeacherCharacter'
import type { Conversation, ConversationMessage } from '../../types'
import { teacherPersonaMeta } from '../persona/personas'

/**
 * 答疑的唯一状态源。
 *
 * 首页「问 AI」、答疑页、悬浮答疑坞三个入口都读写这一份会话，
 * 提问统一走 POST /conversations/{id}/messages（落库 + 历史 + 来源），
 * 不再保留只存内存的第二条链路。
 */

export type AskScope = {
  materialId?: string
  pageNumber?: number
  learningGoal?: string
}

export type ConversationState = {
  conversations: Conversation[]
  conversationId?: string
  /** 可直接渲染的消息列表；会话为空时给当前老师的开场白（本地注入，不入库） */
  messages: ConversationMessage[]
  busy: boolean
  /** 会话与历史是否已就绪。首条问题宜等到就绪，避免与建会话竞态 */
  ready: boolean
  error?: string
  selectConversation: (id: string) => Promise<void>
  /** 发送提问；返回 false 表示未发出（调用方可把文本还回输入框） */
  ask: (text: string, scope?: AskScope) => Promise<boolean>
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
  const busyRef = useRef(false)
  const creatingRef = useRef<Promise<string> | null>(null)

  /* 切换课程：重建会话上下文。空课程建立首个会话，保证后续提问总有落点 */
  useEffect(() => {
    let active = true
    setConversations([])
    setConversationId(undefined)
    setHistory([])
    setError(undefined)
    setReady(false)
    creatingRef.current = null
    if (!courseId) {
      setReady(true)
      return () => { active = false }
    }
    void api.listConversations(courseId).then(async (items) => {
      const next = items.length > 0 ? items : [await api.createConversation(courseId)]
      if (!active) return
      setConversations(next)
      setConversationId(next[0].id)
      const loaded = await api.listConversationMessages(next[0].id)
      if (!active) return
      setHistory(loaded)
      setReady(true)
    }).catch((cause: unknown) => {
      if (!active) return
      setError(cause instanceof Error ? cause.message : '会话读取失败')
      setReady(true)
    })
    return () => { active = false }
  }, [courseId])

  const selectConversation = useCallback(async (id: string) => {
    setConversationId(id)
    setBusy(true)
    setError(undefined)
    try {
      setHistory(await api.listConversationMessages(id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '会话读取失败')
    } finally {
      setBusy(false)
    }
  }, [])

  /* 会话尚未建立就发问时补建一个（悬浮坞可能在异步建会话完成前就提交） */
  const ensureConversation = useCallback(async (): Promise<string | undefined> => {
    if (!courseId) return undefined
    if (conversationId) return conversationId
    if (creatingRef.current) return creatingRef.current
    const pending = api.createConversation(courseId).then((created) => {
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
    busyRef.current = true
    setBusy(true)
    setError(undefined)
    try {
      const targetId = await ensureConversation()
      if (!targetId || courseRef.current !== requestCourseId) return false
      const askedAt = Date.now()
      setHistory((current) => [...current, {
        id: `local-user-${askedAt}`,
        conversation_id: targetId,
        role: 'user',
        content: question,
        learning_goal: scope.learningGoal ?? null,
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
        material_id: scope.materialId,
        page_number: scope.pageNumber,
        learning_goal: scope.learningGoal,
        allow_web: true,
        idempotency_key: `${targetId}-${askedAt}`,
      })
      if (courseRef.current !== requestCourseId) return true
      setHistory((current) => [...current, answer])
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
  }, [courseId, teacherPersona, ensureConversation])

  /* 会话为空时由前端补一条开场白（不入库）；已有历史则原样展示 */
  const messages = useMemo(
    () => (history.length > 0 ? history : [greetingMessage(conversationId, greeting)]),
    [history, conversationId, greeting],
  )

  return { conversations, conversationId, messages, busy, ready, error, selectConversation, ask }
}
